#ifndef SR_RDT_SENDER_H
#define SR_RDT_SENDER_H

#include "RdtSender.h"
#include "DataStructure.h"
#include <vector>
#include <map>

class SRRdtSender : public RdtSender
{
private:
    int nextSeqNum;                // 下一个发送序号
    int baseSeqNum;                // 窗口起始序号
    int seqNumBits;                // 序号二进制位数
    int windowSize;                // 窗口大小
    std::vector<Packet> pkts;      // 已发送但未确认的分组
    std::vector<bool> ackStatus;   // 每个分组的确认状态
    std::vector<bool> timerStatus; // 每个分组的定时器状态
    int modulus;

public:
    bool getWaitingState() override;
    bool send(const Message &message) override;
    void receive(const Packet &ackPkt) override;
    void timeoutHandler(int seqNum) override;

    SRRdtSender();
    virtual ~SRRdtSender();

private:
    bool inWindow(int seqNum) const;
    void slideWindow();
    void printWindowState() const;
};

#endif