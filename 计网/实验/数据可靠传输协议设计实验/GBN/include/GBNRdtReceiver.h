#ifndef GBNRDTRECEIVER_H
#define GBNRDTRECEIVER_H

#include "RdtReceiver.h"
#include "DataStructure.h"

class GBNRdtReceiver : public RdtReceiver
{
private:
    int expectedSeqNum; // 期望接收的下一个序列号
    int seqSize;        // 序列号空间大小(2^k)
    Packet lastAckPkt;  // 上次发送的确认包

public:
    // 接收报文，将被NetworkService调用
    void receive(const Packet &packet) override;

    // 构造函数
    GBNRdtReceiver(int seqBits = 3);

    // 析构函数
    virtual ~GBNRdtReceiver() override;
};

#endif // GBNRDTRECEIVER_H