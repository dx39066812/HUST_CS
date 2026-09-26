#ifndef GBNRDTSENDER_H
#define GBNRDTSENDER_H

#include "RdtSender.h"
#include "DataStructure.h"
#include <vector>

class GBNRdtSender : public RdtSender
{
private:
    int base;                    // 窗口基序号（最早未确认的包）
    int nextSeqNum;              // 下一个要发送的序号
    int N;                       // 窗口长度
    int seqSize;                 // 序号空间大小（2^k）
    std::vector<Packet> packets; // 发送窗口内的数据包缓存
    std::vector<bool> ackStatus; // 确认状态（true表示已确认）

    void printWindowState();

public:
    // 发送应用层下来的Message
    bool send(const Message &message) override;

    // 接受确认Ack
    void receive(const Packet &ackPkt) override;

    // Timeout handler
    void timeoutHandler(int seqNum) override;

    // 返回RdtSender是否处于等待状态
    bool getWaitingState() override;

    // 构造函数
    GBNRdtSender(int windowSize = 4, int seqBits = 3);

    // 析构函数
    virtual ~GBNRdtSender() override;
};

#endif // GBNRDTSENDER_H