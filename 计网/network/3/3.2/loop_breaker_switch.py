from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet
from os_ken.lib.packet import arp
from os_ken.lib.packet import ether_types
import time 

ETHERNET = ethernet.ethernet.__name__
ETHERNET_MULTICAST = "ff:ff:ff:ff:ff:ff"
ARP = arp.arp.__name__


class Switch_Dict(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(Switch_Dict, self).__init__(*args, **kwargs)
        self.flag = 0 # only modify once
        # maybe you need a global data structure to save the mapping
        # just data structure in mission 1
        self.mac_to_port = {}

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        dp = datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority,
                                idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout,
                                match=match, instructions=inst)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
                


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        target_port = 3  # 修改这个端口号（3或4）

        # the identity of switch
        dpid = dp.id
        # the port that receive the packet
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        if eth_pkt.ethertype == ether_types.ETH_TYPE_IPV6:
            return
        # get the mac
        dst = eth_pkt.dst
        src = eth_pkt.src
        
        self.logger.info("交换机: s%d, 入端口: %d, 源MAC: %s, 目标MAC: %s", dpid, in_port,src, dst)

        # you need to code here to avoid broadcast loop to finish mission 2
        # === 禁用端口功能 ===
        if dpid == 1 and self.flag == 0:
            
            # 创建端口禁用消息
            port_mod = parser.OFPPortMod(
                datapath=dp,
                port_no=target_port,
                hw_addr='00:00:00:00:00:00', 
                config=ofp.OFPPC_PORT_DOWN,   
                mask=ofp.OFPPC_PORT_DOWN,     
                advertise=0                   
            )
            dp.send_msg(port_mod)
            
            time.sleep(0.5)
            self.flag = 1  # 设置标志位，确保只执行一次
            self.logger.info("      已禁用交换机 s%d 的端口 %d", dpid, target_port)


        ## 注意
        if dpid == 1 and in_port == target_port:
            return
        


        # self-learning
        # you need to code here to avoid the direct flooding
        # having fun
        # :)
        # just code in mission 1

        # 建立此交换机的 mac->port 映射表
        self.mac_to_port.setdefault(dpid, {})
    
        # 学习源 MAC → 入端口
        self.mac_to_port[dpid][src] = in_port
    
        # 是否已知目标 MAC？
        out_port = self.mac_to_port[dpid].get(dst)
        if out_port:
            # 已学习：下发流表 + 打印日志
            match = parser.OFPMatch(eth_dst=dst)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(dp, 10, match, actions, hard_timeout=0)
            self.logger.info(
                "       下发流表: dpid=%s, src=%s, in_port=%s, dst=%s, out_port=%s", 
                dpid, src, in_port, dst, out_port
            )
        elif dpid == 1:
            # s1洪泛跳过禁用端口
            actions = []
            for port_no in range(1, 5):  # 端口1-4
                if port_no == in_port:
                    continue
                if port_no == target_port:  # 排除禁用端口
                    continue
                actions.append(parser.OFPActionOutput(port_no))
                self.logger.info("      跳过端口%s洪泛",target_port)
        else:
            # 未学习：洪泛
            actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
            self.logger.info("      洪泛")
    
        # ------ 使用 NO_BUFFER + data，避免断言 -------
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=ofp.OFP_NO_BUFFER,
            in_port=in_port,
            actions=actions,
            data=msg.data
        )
        dp.send_msg(out)
