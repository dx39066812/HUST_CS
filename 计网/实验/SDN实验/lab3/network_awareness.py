# 导入所需的模块和类
# os_ken 是SDN控制器框架，类似于OpenFlow控制器
# networkx 是图论计算库，用于构建和分析网络拓扑
# time, copy, hub 是Python标准库或os_ken的辅助模块

from os_ken.base import app_manager  # 导入应用管理器基类，所有OS-Ken应用都需要继承
from os_ken.base.app_manager import lookup_service_brick  # 用于在运行时查找其他OS-Ken应用实例
from os_ken.ofproto import ofproto_v1_3  # OpenFlow协议v1.3版本定义
from os_ken.controller.handler import set_ev_cls  # 装饰器，用于将方法绑定到特定事件
# 导入事件分发器状态常量：
# CONFIG_DISPATCHER: 配置阶段，交换机刚连接时
# MAIN_DISPATCHER: 主要操作阶段，交换机正常运行
# DEAD_DISPATCHER: 死亡状态，交换机断开连接
from os_ken.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER
from os_ken.controller import ofp_event  # OpenFlow事件定义
from os_ken.lib.packet import packet  # 数据包处理类
from os_ken.lib.packet import ethernet, arp  # 以太网和ARP协议相关类
from os_ken.lib import hub  # 协程和线程管理模块（类似asyncio）
from os_ken.topology import event  # 拓扑事件相关
from os_ken.topology.api import get_all_host, get_all_link, get_all_switch  # 获取拓扑信息的API
from os_ken.topology.switches import LLDPPacket  # LLDP协议数据包处理

import networkx as nx  # 导入networkx图论库，并简称为nx
import copy  # 深拷贝模块，用于复制复杂对象
import time  # 时间模块，用于获取时间戳

from os_ken.base.app_manager import lookup_service_brick 

# 定义常量
GET_TOPOLOGY_INTERVAL = 2  # 获取拓扑信息的间隔时间（秒）
SEND_ECHO_REQUEST_INTERVAL = .05  # 发送Echo请求的间隔时间（秒）（任务二使用）
GET_DELAY_INTERVAL = 2  # 获取延迟信息的间隔时间（秒）（任务二使用）

# 定义网络感知应用类，继承自OSKenApp
# 这个类是实验的核心，负责发现网络拓扑、计算路径等
class NetworkAwareness(app_manager.OSKenApp):
    # 指定支持的OpenFlow协议版本
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # 构造函数，初始化类的实例
    # *args 和 **kwargs 是Python的可变参数，用于接收任意数量的参数
    def __init__(self, *args, **kwargs):
        # 调用父类的构造函数
        super(NetworkAwareness, self).__init__(*args, **kwargs)
        
        # 初始化实例变量（成员变量）
        
        # 字典：键是交换机ID（dpid），值是datapath对象
        # datapath代表一个交换机与控制器的连接
        self.switch_info = {}  # dpid: datapath
        
        # 字典：键是（源交换机，目标交换机/主机）元组，值是端口号
        # 例如：{(1,2): 3} 表示从交换机1到交换机2的链路使用端口3
        # 链路两端的端口信息	已知两个设备，找连接端口
        self.link_info = {}  # (s1, s2): s1.port
        
        # 字典：键是（交换机ID，端口号）元组，值是（源交换机，目标交换机）元组
        # 用于通过端口查找对应的链路
        # 端口到链路的映射	通过端口快速找到对应的链路
        self.port_link = {}  # (s1,port): (s1,s2)
        
        # 字典：键是交换机ID，值是连接到主机的端口集合
        # 使用集合（set）避免重复
        # 每个交换机上连接主机的端口	跟踪哪些端口连接了主机（不是交换机）
        self.port_info = {}  # dpid: (ports linked hosts)
        
        # 创建一个无向图对象，用于存储网络拓扑
        # Graph()表示无向图，DiGraph()表示有向图
        self.topo_map = nx.Graph()
        
        # 启动一个协程（轻量级线程）来定期获取拓扑信息
        # hub.spawn()创建并启动一个新协程
        # self._get_topology是要执行的函数
        self.topo_thread = hub.spawn(self._get_topology)
        
        # 路径计算的权重类型，默认是'hop'（跳数）
        # 在任务二中需要改为'delay'（延迟）
        self.weight = 'hop'  # don't forget change it to 'delay'
        
        self.lldp_delay_table = {}  # key: (src_dpid, dst_dpid) -> T_lldp 
        self.switches = {}          # switches app instance 
        self.echo_RTT_table = {}  # key: dpid -> T_echo 
        self.echo_send_timestamp = {} # key: dpid -> send_time 
        self.link_delay_table = {}  # (dpid1, dpid2) -> delay


    # 添加流表项到交换机的方法
    # 这是SDN控制器的核心功能之一
    # 参数说明：
    # - datapath: 交换机对象
    # - priority: 流表项的优先级（数值越大优先级越高）
    # - match: 匹配条件（如源MAC、目的IP等）
    # - actions: 匹配后的动作（如转发到某个端口）
    def add_flow(self, datapath, priority, match, actions):
        # dp是datapath的简称，表示交换机
        dp = datapath
        # ofp是OpenFlow协议的常量定义
        ofp = dp.ofproto
        # parser是消息解析器，用于构造OpenFlow消息
        parser = dp.ofproto_parser

        # 创建一个动作指令列表
        # OFPIT_APPLY_ACTIONS表示立即执行动作
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        # 创建流表修改消息
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst)
        # 发送消息给交换机
        dp.send_msg(mod)

    # 事件处理函数：当交换机连接到控制器时触发
    # @set_ev_cls是装饰器，表示这个方法处理特定事件
    # EventOFPSwitchFeatures: 交换机特性事件（连接时发送）
    # CONFIG_DISPATCHER: 事件分发器状态（配置阶段）
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        # ev是事件对象，msg是事件中的消息
        msg = ev.msg
        # dp是交换机datapath对象
        dp = msg.datapath
        # 获取协议常量和解析器
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        # 创建一个空的匹配条件（匹配所有数据包）
        match = parser.OFPMatch()
        # 创建动作：将数据包发送给控制器
        # OFPP_CONTROLLER: 控制器端口
        # OFPCML_NO_BUFFER: 不缓存数据包
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        # 添加默认流表（优先级为0，匹配所有包，发送给控制器）
        self.add_flow(dp, 0, match, actions)

    # 事件处理函数：处理交换机状态变化
    # EventOFPStateChange: 状态变化事件
    # [MAIN_DISPATCHER, DEAD_DISPATCHER]: 在两种状态下都处理
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        # 获取交换机对象
        dp = ev.datapath
        # 获取交换机ID
        dpid = dp.id

        # 如果状态变为MAIN_DISPATCHER（正常连接状态）
        if ev.state == MAIN_DISPATCHER:
            # 将交换机信息添加到字典中
            self.switch_info[dpid] = dp

        # 如果状态变为DEAD_DISPATCHER（连接断开状态）
        if ev.state == DEAD_DISPATCHER:
            # 从字典中删除该交换机信息
            del self.switch_info[dpid]

    # 获取拓扑信息的私有方法（以下划线开头表示内部方法）
    # 这个方法会定期运行，不断更新网络拓扑
    def _get_topology(self):
        # 用于存储上一次的拓扑信息，用于比较是否有变化
        _hosts, _switches, _links = None, None, None
        
        # 无限循环，定期获取拓扑
        while True:
            # 调用OS-Ken API获取当前拓扑信息
            # hosts: 所有主机列表
            hosts = get_all_host(self)
            # switches: 所有交换机列表
            switches = get_all_switch(self)
            # links: 所有链路列表
            links = get_all_link(self)

            # 如果拓扑没有变化，跳过本次循环
            # 将对象转换为字符串列表进行比较
            if [str(x) for x in hosts] == _hosts and [str(x) for x in switches] == _switches and [str(x) for x in links] == _links:
                continue  # 跳过本次循环，继续下一次
            
            # 更新保存的拓扑信息（转换为字符串形式）
            _hosts = [str(x) for x in hosts]
            _switches = [str(x) for x in switches]
            _links = [str(x) for x in links]

            # 处理交换机信息
            for switch in switches:
                # 为每个交换机初始化端口信息集合（如果不存在）
                # setdefault: 如果键不存在，创建空集合；如果存在，返回已有值
                self.port_info.setdefault(switch.dp.id, set())
                # 记录交换机的所有端口
                # 初始假设所有端口都连接主机
                for port in switch.ports:
                    self.port_info[switch.dp.id].add(port.port_no)

            # 处理主机信息
            for host in hosts:
                # 只处理有IPv4地址的主机
                # host.ipv4是一个列表，可能包含多个IP地址
                if host.ipv4:
                    # 记录主机到链路的映射
                    # (交换机ID, 主机IP): 端口号
                    self.link_info[(host.port.dpid, host.ipv4[0])] = host.port.port_no
                    # 在拓扑图中添加边：主机IP <-> 交换机ID
                    # 添加属性：hop=1（跳数为1）, delay=0（初始延迟为0）, is_host=True（连接的是主机）
                    self.topo_map.add_edge(host.ipv4[0], host.port.dpid, hop=1, delay=0, is_host=True)

            # 处理链路信息（交换机之间的连接）
            for link in links:
                # 发现一个链路（交换机-交换机连接）
                # 那么这个链路的两个端口实际上是连接交换机，不是连接主机
                # 所以要从port_info中删除这些端口
                # discard: 如果元素存在则删除，不存在也不报错
                self.port_info[link.src.dpid].discard(link.src.port_no)
                self.port_info[link.dst.dpid].discard(link.dst.port_no)

                # 记录端口到链路的映射
                # 源交换机端口 -> (源交换机, 目标交换机)
                self.port_link[(link.src.dpid, link.src.port_no)] = (link.src.dpid, link.dst.dpid)
                # 目标交换机端口 -> (目标交换机, 源交换机)
                self.port_link[(link.dst.dpid, link.dst.port_no)] = (link.dst.dpid, link.src.dpid)

                # 记录双向链路的端口信息
                # 源->目标: 源端口号
                self.link_info[(link.src.dpid, link.dst.dpid)] = link.src.port_no
                # 目标->源: 目标端口号
                self.link_info[(link.dst.dpid, link.src.dpid)] = link.dst.port_no

                # 计算链路延迟（TODO: 这里是任务二需要完成的部分）
                '''
                    计算链路delay
                    将delay存入link_delay_table
                    使用self.logger.info打印delay消息
                '''
                delay = self.calculate_link_delay(link.src.dpid, link.dst.dpid)
                
                self.logger.info("Link: %s -> %s, delay: %.5fms",  
                    link.src.dpid, link.dst.dpid, delay*1000) 
                
                self.topo_map.add_edge(
                    link.src.dpid, link.dst.dpid, 
                    hop=1, 
                    delay=delay, 
                    is_host=False
                )
                
                # 在拓扑图中添加边：交换机ID <-> 交换机ID
                # 添加属性：hop=1（跳数为1）, is_host=False（连接的是交换机）
                self.topo_map.add_edge(link.src.dpid, link.dst.dpid, hop=1, is_host=False)

            # 如果权重是'hop'或'delay'，显示拓扑图
            if self.weight == 'hop' or self.weight == 'delay':
                self.show_topo_map()
            
            # 休眠指定时间，然后继续循环
            hub.sleep(GET_TOPOLOGY_INTERVAL)

    # 计算最短路径的方法
    # 参数：
    # - src: 源节点（主机IP或交换机ID）
    # - dst: 目标节点（主机IP或交换机ID）
    # - weight: 权重类型，默认'hop'（跳数）
    def shortest_path(self, src, dst, weight='hop'):
        try:
            # 使用networkx计算所有最短简单路径
            # shortest_simple_paths返回一个生成器，包含所有最短路径
            # list()将生成器转换为列表
            paths = list(nx.shortest_simple_paths(self.topo_map, src, dst, weight=weight))
            # 返回第一条路径（最短路径）
            return paths[0]
        except:
            # 如果出错（如找不到节点或路径），记录日志
            self.logger.info('host not find/no path')

    # 显示拓扑图的方法
    def show_topo_map(self):
        # 打印标题
        self.logger.info('topo map:')
        self.logger.info('{:^10s}  ->  {:^10s}'.format('node', 'node'))
        
        # 遍历拓扑图的所有边
        # self.topo_map.edges返回图中所有边的元组列表
        for src, dst in self.topo_map.edges:
            # 格式化输出边的两个节点
            self.logger.info('{:^10s}      {:^10s}'.format(str(src), str(dst)))
        self.logger.info('\n')  # 打印空行



    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER) 
    def packet_in_hander(self, ev): 
        msg = ev.msg 
        dpid = msg.datapath.id 
        try: 
            src_dpid, src_port_no = LLDPPacket.lldp_parse(msg.data) 
    
            if not self.switches: 
                # get switches 
                self.switches = lookup_service_brick('switches') 
    
            # get lldp_delay 
            for port in self.switches.ports.keys(): 
                if src_dpid == port.dpid and src_port_no == port.port_no: 
                    self.lldp_delay_table[(src_dpid, dpid)] = self.switches.ports[port].delay 
        except: 
            return
        


    def send_echo_request(self, switch): 
        datapath = switch.dp 
        parser = datapath.ofproto_parser 
        ''' 
        构造OFPEchoRequest消息并发送 
        记录send_time 并存入echo_send_timestamp[dpid] 
        ''' 
        dpid = datapath.id

        send_time = time.time()
        self.echo_send_timestamp[dpid] = send_time

        echo_req = parser.OFPEchoRequest(datapath,str(send_time).encode('utf-8'))
        datapath.send_msg(echo_req)



    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER) 
    def handle_echo_reply(self, ev): 
        try: 
            ''' 
            获取装有send_time 的msg，解析所属的交换机的dpid 并
            记录recv_time 
            取出data, 并decode data 获取原始数据 (可选) 
            计算交换机dpid与控制器之间的echo delay并写入echo_
            RTT_table 
            ''' 
            msg = ev.msg
            dp = msg.datapath
            dpid = dp.id
            send_time = self.echo_send_timestamp.get(dpid)
            if send_time:
                self.echo_RTT_table[dpid] = recv_time - send_time
            recv_time = time.time()

        except Exception: 
            self.logger.warning("Failed to handle echo reply")


    # 调用send_echo_request 的⽅式要与你实现的send_echo_request ⽅式一致！ 
    def examine_echo_RTT(self): 
        while True: 
            ''' 
            获取所有的switch 
            对每个switch的echo RTT进行测量 
            睡眠一段时间(SEND_ECHO_REQUEST_INTERVAL) 
            ''' 
            for switch in get_all_switch():
                self.send_echo_request(switch)
            hub.sleep(SEND_ECHO_REQUEST_INTERVAL)

    def calculate_link_delay(self, src_dpid, dst_dpid): 
        ''' 
        取出 LLDP delay与 Echo RTT 
        计算并返回link的delay 
        '''
        try:
            lldp_12 = self.lldp_delay_table.get((src_dpid, dst_dpid), 0)
            lldp_21 = self.lldp_delay_table.get((dst_dpid, src_dpid), 0)

            echo_1 = self.echo_RTT_table.get(src_dpid, 0)
            echo_2 = self.echo_RTT_table.get(dst_dpid, 0)
            
            return max((lldp_12 + lldp_21 - echo_1 - echo_2) / 2, 0)
        except KeyError:
            #lldp_link_delay[(s1, s2)]不存在
            return 0
        



    '''
    以下是你需要完成的任务：
    
    - 添加变量（任务二需要）
        - lldp_delay_table: 存储LLDP测量的延迟
        - echo_RTT_table: 存储Echo往返时间
        - echo_send_timestamp: 存储Echo发送时间
        - link_delay_table: 存储计算出的链路延迟
    
    - lab3.1（任务一）已基本完成
        1. get lldp delay - 需要实现
        2. get echo delay - 需要实现  
        3. calculate link delay - 需要实现
        4. get shortest path with networkx - 已实现
    
    - lab3.2（任务二）
        1. handle `EventOFPPortStatus` - 需要实现
        2. delete flow when port down - 需要实现
    '''