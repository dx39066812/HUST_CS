#include "GBNRdtReceiver.h"
#include "Global.h"
#include "Tool.h"
#include <iostream>

// 构造函数
GBNRdtReceiver::GBNRdtReceiver(int seqBits)
    : expectedSeqNum(0), seqSize(1 << seqBits)
{

    // 初始化上次发送的确认包
    lastAckPkt.acknum = -1; // 初始确认号为-1
    lastAckPkt.checksum = 0;
    lastAckPkt.seqnum = -1; // 忽略该字段

    // 填充payload
    for (int i = 0; i < Configuration::PAYLOAD_SIZE; i++)
    {
        lastAckPkt.payload[i] = '.';
    }
    lastAckPkt.checksum = pUtils->calculateCheckSum(lastAckPkt);

    // 输出初始化信息
    std::cout << "[GBN] receiver initialize: seq space=" << seqSize << std::endl;
}

// 析构函数
GBNRdtReceiver::~GBNRdtReceiver()
{
    std::cout << "[GBN] receiver destruct" << std::endl;
}

void GBNRdtReceiver::receive(const Packet &packet)
{
    int checkSum = pUtils->calculateCheckSum(packet);

    if (checkSum == packet.checksum && packet.seqnum == expectedSeqNum)
    {
        Message msg;
        memcpy(msg.data, packet.payload, sizeof(packet.payload));
        pns->delivertoAppLayer(RECEIVER, msg);

        // 更新期望的序列号
        expectedSeqNum = (expectedSeqNum + 1) % seqSize;

        // 确认号应该是最近成功接收的序号
        lastAckPkt.acknum = (expectedSeqNum - 1 + seqSize) % seqSize;
        lastAckPkt.checksum = 0;
        lastAckPkt.checksum = pUtils->calculateCheckSum(lastAckPkt);

        // 输出调试信息
        std::cout << "[GBN] Receiver updated expectedSeqNum to: " << expectedSeqNum << std::endl;
    }
    else
    {
        // 错误处理逻辑
        // 包出错或不是期望的包
        if (checkSum != packet.checksum)
        {
            pUtils->printPacket("[GBN] receiver received corrupted packet", packet);
        }
        else
        {
            pUtils->printPacket("[GBN] receiver received unexpected seq num", packet);
            std::cout << "[GBN] ecptct seq num: " << expectedSeqNum
                      << ",seq num received: " << packet.seqnum << std::endl;
        }
    }

    // 发送确认包
    pUtils->printPacket("[GBN] Receiver sending acknowledgment", lastAckPkt);
    pns->sendToNetworkLayer(SENDER, lastAckPkt);
}