from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet
from os_ken.lib.packet import arp
from os_ken.lib.packet import ether_types

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

        # s1 的端口映射：在 topo_2 中，s1 与 h1/s2/s3/s4 的链接顺序使得
        # s1 -> h1 为 port 1, s1 -> s2 为 port 2, s1 -> s3 为 port 3, s1 -> s4 为 port 4
        # 目标：禁用 s1 与 s3 的连接（s1 侧端口号为 3）
        self.block_ports = {1: 4}
        self.mac_table = {}    
        self.block_done = set()

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
        
        # you need to code here to avoid broadcast loop to finish mission 2
        if dpid in self.block_ports and dpid not in self.block_done:
            ## begin
            target_port = self.block_ports[dpid]
            self.block_done.add(dpid)
            try:
                # 取得 hw_addr（如果 dp.ports 包含则使用），否则用 00:00:...
                hw_addr = None
                if hasattr(dp, 'ports') and target_port in dp.ports:
                    hw_addr = dp.ports[target_port].hw_addr
                if hw_addr is None:
                    # fallback: 6 zero bytes
                    hw_addr = b'\x00\x00\x00\x00\x00\x00'

                # config: set PORT_DOWN; mask: indicate which bits we change
                port_mod = parser.OFPPortMod(datapath=dp,
                                             port_no=target_port,
                                             hw_addr=hw_addr,
                                             config=ofp.OFPPC_PORT_DOWN,
                                             mask=ofp.OFPPC_PORT_DOWN,
                                             advertise=0)
                dp.send_msg(port_mod)
                self.logger.info("Sent OFPPortMod to set dpid=%s port=%s DOWN (hw_addr=%s)", dpid, target_port, hw_addr)
            except Exception as e:
                # 如果 PortMod 不被支持或失败，退回到安装 ingress-drop 流（至少阻断 ingress）
                self.logger.warning("OFPPortMod failed for dpid=%s port=%s: %s. Falling back to ingress-drop flow.", dpid, target_port, e)
                match_block = parser.OFPMatch(in_port=target_port)
                actions_block = []  # drop
                self.add_flow(dp, 100, match_block, actions_block)
                self.logger.info("Installed ingress-drop on dpid=%s port=%s as fallback", dpid, target_port)
            ## end

        ## 注意
        if dpid in self.block_ports and in_port == self.block_ports[dpid]:
            return

        # self-learning
        # you need to code here to avoid the direct flooding
        # having fun
        # :)
        # just code in mission 1
        ## begin
        if not (dpid in self.block_ports and self.block_ports[dpid] == in_port):
            key = (dpid, src)
            self.mac_table[key] = in_port

        tar_key = (dpid, dst)
        if tar_key in self.mac_table:
            out_port = self.mac_table[tar_key]
            assert in_port != out_port, f"ERROR: mac_table{self.mac_table}, port={in_port}, src={src}, dst={dst}, dpid={dpid}"
            actions = [parser.OFPActionOutput(out_port)]
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst) # dst determines out_port
            self.add_flow(dp, 1, match, actions, hard_timeout=0)
            self.logger.info("(dpid,src_mac,in_port,dst_mac,out_port)=(%s,%s,%s,%s,%s)", dpid, src, in_port, dst, out_port)
        else:
            ####### 千万要注意，不要直接泛洪，否则还是会用到被阻断的端口 ########
            #######        或者有没有别的禁用端口的方法 ？？？         ########
            print(f'flood at {dpid} from port {in_port}')
            # actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
            self.logger.info("Executing Smart Flood on dpid=%s for packet from port %s.", dpid, in_port)
            actions = []
            for port_no in dp.ports:
                if port_no == in_port:
                    continue
                if dpid in self.block_ports and port_no == self.block_ports[dpid]:
                    continue
                actions.append(parser.OFPActionOutput(port_no))

        print(f'***mac_table: {self.mac_table}')
        # [TODO] Maybe msg缓存判断
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=msg.match['in_port'],actions=actions, data=msg.data)
        dp.send_msg(out)
        ## end

