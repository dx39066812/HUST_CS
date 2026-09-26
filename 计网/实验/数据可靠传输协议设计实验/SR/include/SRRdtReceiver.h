#ifndef SR_RDT_RECEIVER_H
#define SR_RDT_RECEIVER_H

#include "RdtReceiver.h"
#include "DataStructure.h"
#include <vector>
#include <map>

class SRRdtReceiver : public RdtReceiver
{
private:
    int expectedSeqNum;             // 期望接收的下一个序号
    int windowSize;                 // 接收窗口大小
    int seqNumBits;                 // 序号二进制位数
    std::vector<Packet> pkts;       // 缓存乱序到达的分组
    std::vector<bool> rcvdStatus;   // 每个分组的接收状态
    std::map<int, Packet> ackCache; // 已发送确认的缓存，用于重传
    int modulus;

public:
    SRRdtReceiver();
    virtual ~SRRdtReceiver();
    void receive(const Packet &packet) override;

private:
    bool inWindow(int seqNum) const;
    void sendAck(int seqNum); // 发送对特定序号的确认
    void deliverToApplication();
    void slideWindow();
    void printWindowState() const;
};

#endif