from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, HANDSHAKE_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet, arp, ipv4, ether_types
from os_ken.controller import ofp_event
from os_ken.topology import event
import sys
from network_awareness import NetworkAwareness
import networkx as nx

from os_ken.topology.api import get_all_switch

ETHERNET = ethernet.ethernet.__name__
ETHERNET_MULTICAST = "ff:ff:ff:ff:ff:ff"
ARP = arp.arp.__name__
class ShortestDelay(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'network_awareness': NetworkAwareness
    }

    def __init__(self, *args, **kwargs):
        super(ShortestDelay, self).__init__(*args, **kwargs)
        self.network_awareness = kwargs['network_awareness']
        self.weight = 'delay' # do not forget to change to 'delay' if you want to use delay
        self.mac_to_port = {}
        self.sw = {}
        self.path=None

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        dp = datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=dp, priority=priority,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            match=match, instructions=inst)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        dpid = dp.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        arp_pkt = pkt.get_protocol(arp.arp)
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)

        pkt_type = eth_pkt.ethertype

        # layer 2 self-learning
        dst_mac = eth_pkt.dst
        src_mac = eth_pkt.src


        if isinstance(arp_pkt, arp.arp):
            self.handle_arp(msg, in_port, dst_mac,src_mac, pkt,pkt_type)

        if isinstance(ipv4_pkt, ipv4.ipv4):
            self.handle_ipv4(msg, ipv4_pkt.src, ipv4_pkt.dst, pkt_type)

    def handle_arp(self, msg, in_port, dst, src, pkt, pkt_type):
        """
        增强版：保留你原来的解析 & 日志，但不改变实验要求的行为（仍然仅做环路检测 + 洪泛）
        """
        datapath = msg.datapath
        dpid = datapath.id
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        arp_pkt = pkt.get_protocol(arp.arp)
        if not arp_pkt:
            return

        opcode = arp_pkt.opcode

        # 继续使用 (dpid, src_mac, dst_mac) 检测环路
        key = (dpid, src, dst)

        if key in self.sw:
            if self.sw[key] != in_port:
                self.logger.info(
                    "       ARP loop detected -> DROP (dpid=%s, src=%s, dst=%s, now=%s, before=%s)",
                    dpid, src, dst, in_port, self.sw[key]
                )
                return
        else:
            self.sw[key] = in_port

        # 不学习 MAC！！！避免改变正常行为（这会破坏 ARP Reply 路径）
        # self.mac_to_port[dpid][src] = in_port    # ❌ 去掉

        # 无论 Request/Reply，都按实验要求：洪泛
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data
        )
        datapath.send_msg(out)

    def handle_ipv4(self, msg, src_ip, dst_ip, pkt_type):
        parser = msg.datapath.ofproto_parser

        dpid_path = self.network_awareness.shortest_path(src_ip, dst_ip,weight=self.weight)
        if not dpid_path:
            return



        self.path=dpid_path
        # get port path:  h1 -> in_port, s1, out_port -> h2
        port_path = []
        for i in range(1, len(dpid_path) - 1):
            in_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i - 1])]
            out_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i + 1])]
            port_path.append((in_port, dpid_path[i], out_port))
        self.show_path(src_ip, dst_ip, port_path)

        # calc path delay and print
        # style:
        #   "delay = %.5fms"
        #   "time = %.5fms"
        '''
            利用dpid_path(最短路)和link_delay_table计算path delay, path RTT
            输出link delay dict, path delay， path RTT
            输出语句示例:
            self.logger.info('link delay dict: %s', )
            self.logger.info('path delay = %.5fms', )
            self.logger.info('path RTT = %.5fms', )
        '''
        # 计算路径各链路时延
        link_delay_dict = {}
        path_delay = 0.0  # 该路径的单程总时延 (second)

        for i in range(1, len(dpid_path) - 1):
            src = dpid_path[i]
            dst = dpid_path[i + 1]

            # 如果该链路在拓扑图中存在，则读取 delay 属性
            if self.network_awareness.topo_map.has_edge(src, dst):
                delay = self.network_awareness.topo_map[src][dst].get('delay', 0)
                
                # 记录链路延迟（单位转为 ms）
                link_delay_dict[f"s{src} -> s{dst}"] = delay * 1000  
                
                # 累加该链路的单程时延 (秒)
                path_delay += delay

        # 计算 RTT（往返）
        path_RTT = path_delay * 2

        # 输出链路时延表 & 路径总时延
        self.logger.info("link delay dict: %s", link_delay_dict)
        self.logger.info("path delay = %.5f ms", path_delay * 1000)
        self.logger.info("path RTT  = %.5f ms", path_RTT * 1000)

        

        # send flow mod
        for node in port_path:
            in_port, dpid, out_port = node
            self.send_flow_mod(parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port)
            self.send_flow_mod(parser, dpid, pkt_type, dst_ip, src_ip, out_port, in_port)

        # send packet_out
        _, dpid, out_port = port_path[-1]
        dp = self.network_awareness.switch_info[dpid]
        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data)
        dp.send_msg(out)

    def send_flow_mod(self, parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port):
        dp = self.network_awareness.switch_info[dpid]
        match = parser.OFPMatch(
            in_port=in_port, eth_type=pkt_type, ipv4_src=src_ip, ipv4_dst=dst_ip)
        actions = [parser.OFPActionOutput(out_port)]
        self.add_flow(dp, 1, match, actions, 10, 30)

    def show_path(self, src, dst, port_path):
        self.logger.info('path: {} -> {}'.format(src, dst))
        path = src + ' -> '
        for node in port_path:
            path += '{}:s{}:{}'.format(*node) + ' -> '
        path += dst
        self.logger.info(path)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER) 
    def port_status_handler(self, ev): 
        msg = ev.msg 
        datapath = msg.datapath 
        ofproto = datapath.ofproto 
        if msg.reason in [ofproto.OFPPR_ADD, ofproto.OFPPR_MODIFY]: 
            # 端口新增或修改(link up 和 link down 均属于对端口状态的修改) 
            datapath.ports[msg.desc.port_no] = msg.desc 
            ''' 
            情况拓扑图。（调用topo_map使用`self.network_awaren
            ess.topo_map`） 
            删除所有流表 
            删除sw 
            删除mac_to_port 
            ''' 
            self.logger.info("交换机 %s 端口 %s 状态改变，删除拓扑图、流表、sw、mac_to_port"
                             ,datapath.id, msg.desc.port_no)
            
            self.network_awareness.topo_map.clear()
            self.delete_all_flow()
            self.sw.clear()
            self.mac_to_port.clear()

        elif msg.reason == ofproto.OFPPR_DELETE: 
            datapath.ports.pop(msg.desc.port_no, None) 
        else: 
            return
        
    def delete_all_flow(self): 
        ''' 
        参考_get_topology() in network_awareness.py 
        遍历所有switch的端口，然后删除删除所有流表项 
        ''' 
        for switch in get_all_switch(self.network_awareness):
            dp = switch.dp
            for port in switch.ports:
                if port.port_no != dp.ofproto.OFPP_LOCAL:
                    self.delete_flow(dp, port.port_no)


    def delete_flow(self, datapath, port_no): 
        ofproto = datapath.ofproto 
        parser = datapath.ofproto_parser 
    
        try: 
            ''' 
            1. 构造匹配字段 
            2. 设置OFPFlowMod消息 
            3. 发送消息到交换机 
            注意：你需要发送两个消息，一个用于删除in_port的流表，另一个用于删除action(out_port)的流表 
            ''' 

            match_in = parser.OFPMatch(in_port=port_no)
            mod_in = parser.OFPFlowMod(
                datapath=datapath,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=match_in
            )
            datapath.send_msg(mod_in)
            
            match_out = parser.OFPMatch()
            mod_out = parser.OFPFlowMod(
                datapath=datapath,
                command=ofproto.OFPFC_DELETE,
                out_port=port_no, 
                out_group=ofproto.OFPG_ANY,
                match=match_out
            )
            datapath.send_msg(mod_out)
            
        except Exception as e: 
                self.logger.error("Failed to delete flow entries associated with port %s on switch %s: %s"
                                  , port_no, datapath.id, str(e)) 