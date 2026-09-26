# 导入OS-Ken应用管理器，用于创建控制器应用
from os_ken.base import app_manager
# 导入OpenFlow事件相关模块
from os_ken.controller import ofp_event
# 导入事件分发器状态常量：
# CONFIG_DISPATCHER: 配置阶段，交换机刚连接时
# MAIN_DISPATCHER: 主要操作阶段，交换机正常运行
# DEAD_DISPATCHER: 死亡状态，交换机断开连接
# HANDSHAKE_DISPATCHER: 握手阶段，交换机与控制器的初始连接
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, HANDSHAKE_DISPATCHER
# 导入装饰器，用于将函数注册为事件处理器
from os_ken.controller.handler import set_ev_cls
# 导入OpenFlow协议v1.3版本
from os_ken.ofproto import ofproto_v1_3
# 导入数据包处理相关模块
from os_ken.lib.packet import packet  # 通用数据包类
from os_ken.lib.packet import ethernet, arp, ipv4, ether_types  # 各种协议类
# 导入拓扑事件模块
from os_ken.topology import event
# 导入系统模块
import sys
# 导入自定义的网络感知模块，这是任务一的核心
from network_awareness import NetworkAwareness
# 导入图论库，用于路径计算
import networkx as nx


# 定义常量：以太网协议名称
ETHERNET = ethernet.ethernet.__name__  # 字符串'ethernet'
# 定义常量：以太网广播MAC地址
ETHERNET_MULTICAST = "ff:ff:ff:ff:ff:ff"
# 定义常量：ARP协议名称
ARP = arp.arp.__name__  # 字符串'arp'


# 定义最少跳数路径控制器类，继承自OSKenApp
class LeastHops(app_manager.OSKenApp):
    # 指定支持的OpenFlow协议版本为v1.3
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    # 定义应用上下文，使NetworkAwareness应用可用
    # 这样LeastHops应用可以访问NetworkAwareness应用的实例
    _CONTEXTS = {
        'network_awareness': NetworkAwareness
    }

    # 构造函数，初始化应用
    def __init__(self, *args, **kwargs):
        # 调用父类的构造函数
        super(LeastHops, self).__init__(*args, **kwargs)
        
        # 从上下文中获取network_awareness应用实例
        self.network_awareness = kwargs['network_awareness']
        
        # 设置权重类型为'hop'（跳数）
        # 注意：如果要使用延迟权重，需要改为'delay'
        self.weight = 'hop' # do not forget to change to 'delay' if you want to use delay
        
        # MAC地址到端口映射表
        # 格式: {(dpid, mac地址): 端口号}
        self.mac_to_port = {}
        
        # 用于记录ARP请求转发情况的表，防止环路
        # 格式: {(dpid, src_mac, dst_ip): in_port}
        self.sw = {}
        
        # 存储当前计算出的路径
        self.path = None

    # 添加流表项到交换机的方法
    # 参数说明:
    # - datapath: 交换机对象
    # - priority: 流表项优先级（数值越大优先级越高）
    # - match: 匹配条件
    # - actions: 执行动作
    # - idle_timeout: 空闲超时时间（秒），如果流表项在该时间内没有匹配到数据包，将被删除
    # - hard_timeout: 硬超时时间（秒），无论是否匹配到数据包，超过该时间流表项将被删除
    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        dp = datapath  # 交换机对象
        ofp = dp.ofproto  # OpenFlow协议常量
        parser = dp.ofproto_parser  # 消息解析器

        # 创建动作指令列表
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        
        # 创建流表修改消息
        mod = parser.OFPFlowMod(
            datapath=dp, priority=priority,
            idle_timeout=idle_timeout,  # 空闲超时
            hard_timeout=hard_timeout,  # 硬超时
            match=match, instructions=inst)
        
        # 发送流表修改消息给交换机
        dp.send_msg(mod)

    # 数据包进入事件处理函数
    # 当交换机收到不匹配任何流表项的数据包时，会将其发送给控制器
    # @set_ev_cls装饰器指定这个方法处理EventOFPPacketIn事件
    # MAIN_DISPATCHER表示在主要操作阶段处理
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        # ev: 事件对象
        msg = ev.msg  # PacketIn消息
        dp = msg.datapath  # 交换机对象
        ofp = dp.ofproto  # OpenFlow协议常量
        parser = dp.ofproto_parser  # 消息解析器

        # 获取交换机ID和数据包进入的端口号
        dpid = dp.id  # 交换机ID
        in_port = msg.match['in_port']  # 数据包进入的端口

        # 解析数据包
        pkt = packet.Packet(msg.data)  # 创建数据包对象
        eth_pkt = pkt.get_protocol(ethernet.ethernet)  # 获取以太网层信息
        arp_pkt = pkt.get_protocol(arp.arp)  # 获取ARP层信息
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)  # 获取IPv4层信息

        # 获取以太网类型（用于识别是ARP还是IP数据包）
        pkt_type = eth_pkt.ethertype

        # 获取源MAC地址和目的MAC地址
        dst_mac = eth_pkt.dst  # 目的MAC地址
        src_mac = eth_pkt.src  # 源MAC地址

        
        # 根据数据包类型调用不同的处理函数
        if isinstance(arp_pkt, arp.arp):  # 如果是ARP数据包
            self.logger.info("ARP数据包——交换机: s%d, 入端口: %d, 源MAC: %s, 目标MAC: %s", 
                dpid, in_port, src_mac, dst_mac)
            self.handle_arp(msg, in_port, dst_mac, src_mac, pkt, pkt_type)
        
        if isinstance(ipv4_pkt, ipv4.ipv4):  # 如果是IPv4数据包
            self.logger.info("IPv4数据包——交换机: s%d, 入端口: %d, 源MAC: %s, 目标MAC: %s", 
                dpid, in_port, src_mac, dst_mac)
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



    # IPv4数据包处理函数
    # 主要任务：计算最短路径，下发流表，转发数据包
    def handle_ipv4(self, msg, src_ip, dst_ip, pkt_type):
        # 获取消息解析器
        parser = msg.datapath.ofproto_parser


        self.logger.info("      IPv4包 - 源IP: %s, 目标IP: %s ",
                        src_ip, dst_ip)


        # 调用network_awareness的shortest_path方法计算最短路径
        # dpid_path: 路径上的节点列表，包括主机IP和交换机ID
        # 例如: ['10.0.0.2', 1, 2, 3, 4, '10.0.0.9']
        dpid_path = self.network_awareness.shortest_path(src_ip, dst_ip, weight=self.weight)
        
        # 如果没有找到路径，直接返回
        if not dpid_path:
            return

        # 保存路径供后续使用
        self.path = dpid_path
        
        # 将节点路径转换为端口路径
        # port_path格式: [(in_port, dpid, out_port), ...]
        port_path = []
        for i in range(1, len(dpid_path) - 1):
            # 计算进入当前交换机的端口（从前一个节点来）
            in_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i - 1])]
            # 计算离开当前交换机的端口（到下一个节点去）
            out_port = self.network_awareness.link_info[(dpid_path[i], dpid_path[i + 1])]
            # 添加到端口路径列表
            port_path.append((in_port, dpid_path[i], out_port))
        
        # 显示路径信息
        self.show_path(src_ip, dst_ip, port_path)

        # 计算路径延迟并打印（TODO: 这是任务二的内容）
        # 需要输出的格式:
        #   "delay = %.5fms"
        #   "time = %.5fms"
        '''
            your code
        '''

        # 发送流表修改消息，为路径上的每个交换机添加流表项
        for node in port_path:
            in_port, dpid, out_port = node  # 解包元组
            
            # 为正向流量（从源到目的）添加流表
            self.send_flow_mod(parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port)
            # 为反向流量（从目的到源）添加流表
            self.send_flow_mod(parser, dpid, pkt_type, dst_ip, src_ip, out_port, in_port)

        # 发送PacketOut消息，立即转发当前数据包
        # 获取路径上最后一个交换机（离目的主机最近的交换机）
        # 当前数据包已经在控制器手中，不需要再经过前面的交换机。控制器可以直接告诉最后一个交换机将数据包发送给目的主机。
        _, dpid, out_port = port_path[-1]
        dp = self.network_awareness.switch_info[dpid]  # 获取交换机对象
        
        # 创建输出动作列表（从指定端口转发）
        actions = [parser.OFPActionOutput(out_port)]
        
        # 创建PacketOut消息
        out = parser.OFPPacketOut(
            datapath=dp,  # 交换机对象
            buffer_id=msg.buffer_id,  # 数据包缓冲区ID（如果交换机缓存了数据包）
            in_port=in_port,  # 输入端口（注意：这里in_port是最后一次循环的值）
            actions=actions,  # 转发动作
            data=msg.data)  # 数据包内容
        
        # 发送PacketOut消息给交换机
        dp.send_msg(out)

    # 发送流表修改消息的辅助函数
    def send_flow_mod(self, parser, dpid, pkt_type, src_ip, dst_ip, in_port, out_port):
        # 根据交换机ID获取交换机对象
        dp = self.network_awareness.switch_info[dpid]
        
        # 创建匹配条件：
        # - in_port: 数据包进入的端口
        # - eth_type: 以太网类型（如IPv4或ARP）
        # - ipv4_src: 源IP地址
        # - ipv4_dst: 目的IP地址
        match = parser.OFPMatch(
            in_port=in_port, 
            eth_type=pkt_type, 
            ipv4_src=src_ip, 
            ipv4_dst=dst_ip)
        
        # 创建转发动作：从指定端口输出
        actions = [parser.OFPActionOutput(out_port)]
        
        # 添加流表项，设置超时时间（10秒空闲超时，30秒硬超时）
        self.add_flow(dp, 1, match, actions, 10, 30)

    # 显示路径信息的辅助函数
    def show_path(self, src, dst, port_path):
        # 打印路径起点和终点
        self.logger.info('      path: {} -> {}'.format(src, dst))
        
        # 构建路径字符串
        path = '      ' + src + ' -> '
        # 遍历端口路径，格式化每个节点
        for node in port_path:
            # node是(in_port, dpid, out_port)元组
            # {}:s{}:{} 是格式化字符串，对应in_port, dpid, out_port
            path += '{}:s{}:{}'.format(*node) + ' -> '
        
        # 添加路径终点
        path += dst
        
        # 打印完整路径
        self.logger.info(path)