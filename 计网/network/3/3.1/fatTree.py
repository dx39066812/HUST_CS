from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel

class FatTreeTopo(Topo):
    def build(self,k=4):
        pod_num = k
        core_s = int((k/2)**2)
        agg_per_pod = int(k/2)
        edge_per_pod = int(k/2)
        host_per_edge = int(k/2)

        #核心层switch
        core_s_list = []
        for i in range(core_s_list):
            sw = self.addSwitch(f'c{i+1}')
            core_s_list.append(sw)

        #Pod
        for pod in range(pod_num):
            agg_s = []
            edge_s = []

            #聚合层
            for i in range(agg_per_pod):
                sw = self.addSwitch(f'a{pod}_{i}')
                agg_s.append(sw)

            #边缘层
            for i in range(edge_per_pod):
                sw = self.addSwitch(f'e{pod}_{i}')
                edge_s.append(sw)

            #连接edge和host
            for i,edge in enumerate(edge_s):
                for j in range(host_per_edge):
                    host_id = pod * edge_per_pod * host_per_edge + i * host_per_edge + j + 1
                    host = self.addHost(f'h{host_id}')
                    self.addLink(edge,host)
            
            #连接edge和aggregation
            for edge in edge_s:
                for agg in agg_s:
                    self.addLink(edge,agg)
            
            #连接aggregation和core
            for i, agg in enumerate(agg_s):
                for j in range(int(k/2)):
                    core_index = i*int(k/2) + j
                    self.addLink(agg,core_s_list[core_index])

def run():
        topo = FatTreeTopo(k=4)
        net = Mininet(topo=topo,controller=None)
        net.start()
        print("*******网络启动*******")
        net.pingAll()
        CLI(net)
        net.stop() 

if __name__=='__main__':
    setLogLevel('info')
    run()