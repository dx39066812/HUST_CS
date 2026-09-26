from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet
from os_ken.lib.packet import arp
from os_ken.lib.packet import ether_types

# 协议名称常量
ETHERNET = ethernet.ethernet.__name__
ETHERNET_MULTICAST = "ff:ff:ff:ff:ff:ff"   # 广播 MAC
ARP = arp.arp.__name__                     # ARP 协议名


class Switch_Dict(app_manager.OSKenApp):
    # 仅支持 OpenFlow 1.3
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(Switch_Dict, self).__init__(*args, **kwargs)

        # sw 表用于记录 ARP Request 的转发历史
        # key: (dpid, src_mac, dst_ip)  →  value: in_port
        self.sw = {}

        # 交换机的 MAC 学习表
        # mac_to_port = {dpid : {mac : port}}
        self.mac_to_port = {}
        

    # 添加流表项
    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        dp = datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        # 指令：执行动作列表
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        # 构造流表项
        mod = parser.OFPFlowMod(datapath=dp, priority=priority,
                                idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout,
                                match=match, instructions=inst)
        # 发给交换机
        dp.send_msg(mod)

    # 交换机连接时下发 table-miss 流表项
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # 匹配所有
        match = parser.OFPMatch()

        # 未匹配到时发送到控制器
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]

        # 发出 table-miss
        self.add_flow(dp, 0, match, actions)

    # Packet-In 事件处理函数
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # 交换机编号 (DPID)
        dpid = dp.id

        # 入端口
        in_port = msg.match['in_port']

        # 解析数据包
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)

        # 忽略 LLDP（用于拓扑发现）
        if eth_pkt.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        # 忽略 IPv6
        if eth_pkt.ethertype == ether_types.ETH_TYPE_IPV6:
            return

        # 源 MAC 和 目的 MAC
        dst = eth_pkt.dst
        src = eth_pkt.src

        self.logger.info("交换机: s%d, 入端口: %d, 源MAC: %s, 目标MAC: %s", dpid, in_port,src, dst)

        # 将协议对象提取为 dict（ARP、IP 等）
        header_list = dict((p.protocol_name, p) for p in pkt.protocols if type(p) != str)
        
        # --------------------------
        #   环路检测
        # --------------------------
        if dst == ETHERNET_MULTICAST and ARP in header_list:
            # 若是 ARP Request 广播帧，则进入环路检测
            arp_pkt = header_list[ARP]
            arp_dst_ip = arp_pkt.dst_ip
            
            # 以 (交换机编号, 源 MAC, 目的 IP) 作为 key
            key = (dpid, src, arp_dst_ip)
            
            # 如果之前记录过
            if key in self.sw:
                # 且这次 in_port 与之前不同 → 说明 ARP 在环路中被重复转发
                if self.sw[key] != in_port:
                    self.logger.info(
                        "       检测到环路,丢弃ARP请求: dpid=%s, src=%s, dst_ip=%s, "
                        "in_port=%s, previous port=%s", 
                        dpid, src, arp_dst_ip, in_port, self.sw[key]
                    )
                    # 直接丢弃，不转发
                    return
            else:
                # 第一次出现，记录其 in_port
                self.sw[key] = in_port
                self.logger.info(
                    "       记录ARP请求: dpid=%s, src=%s, dst_ip=%s, in_port=%s", 
                    dpid, src, arp_dst_ip, in_port
                )
        
        # --------------------------
        #   自学习交换机
        # --------------------------

        # 为该交换机初始化 MAC 表
        self.mac_to_port.setdefault(dpid, {})
        
        # 学习源 MAC → ingress port
        self.mac_to_port[dpid][src] = in_port
        
        # 查找目的 MAC 是否存在
        if dst in self.mac_to_port[dpid]:
            # 若已学习，则直接查表转发
            out_port = self.mac_to_port[dpid][dst]
            
            # 打印匹配信息
            self.logger.info(
                "       下发流表: dpid=%s, src=%s, in_port=%s, dst=%s, out_port=%s", 
                dpid, src, in_port, dst, out_port
            )
            
            # 构造匹配规则 (入端口 + 目的 MAC)
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            # 输出动作
            actions = [parser.OFPActionOutput(out_port)]
            
            # 下发流表项
            self.add_flow(dp, 1, match, actions)
            
            # 同时转发当前包
            out = parser.OFPPacketOut(
                datapath=dp,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data
            )
            dp.send_msg(out)
        else:
            # 未学习目的 MAC → 洪泛
            self.logger.info("      洪泛")
            actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
            out = parser.OFPPacketOut(
                datapath=dp,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data
            )
            dp.send_msg(out)
