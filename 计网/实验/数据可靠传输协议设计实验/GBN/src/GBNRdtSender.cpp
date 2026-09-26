#include "GBNRdtSender.h"
#include "Global.h"
#include "Tool.h"
#include <iostream>

// 构造函数
GBNRdtSender::GBNRdtSender(int windowSize, int seqBits)
    : base(0), nextSeqNum(0), N(windowSize), seqSize(1 << seqBits)
{
    packets.resize(seqSize);
    ackStatus.resize(seqSize, false);

    // 输出初始化信息
    std::cout << "[GBN] sender initialize: windows size " << N
              << ", seq space=" << seqSize << std::endl;
}

// 析构函数
GBNRdtSender::~GBNRdtSender()
{
    std::cout << "[GBN] sender destruct" << std::endl;
}

// 发送应用层下来的Message
bool GBNRdtSender::send(const Message &message)
{
    if (getWaitingState())
    {
        pUtils->printPacket("[GBN] windows is full, refuse sending", Packet());
        return false; // 窗口已满，拒绝发送
    }

    // 构造数据包
    Packet pkt;
    pkt.seqnum = nextSeqNum;
    pkt.acknum = -1; // 无效值
    memcpy(pkt.payload, message.data, sizeof(message.data));
    pkt.checksum = pUtils->calculateCheckSum(pkt);

    // 缓存包并更新状态
    packets[nextSeqNum % seqSize] = pkt;
    ackStatus[nextSeqNum % seqSize] = false;

    pUtils->printPacket("[GBN] send packet", pkt);
    pns->sendToNetworkLayer(RECEIVER, pkt);

    // 如果是窗口第一个包，启动定时器
    if (base == nextSeqNum)
    {
        pns->startTimer(SENDER, Configuration::TIME_OUT, base);
        pUtils->printPacket("[GBN] start timer,seq", pkt);
    }

    nextSeqNum = (nextSeqNum + 1) % seqSize;

    // 输出当前窗口状态
    std::cout << "[GBN] windows state: base=" << base
              << ", nextSeqNum=" << nextSeqNum
              << ", windows size =" << (nextSeqNum - base + seqSize) % seqSize
              << "/" << N << std::endl;
    printWindowState();

    return true;
}

// 接受确认Ack
void GBNRdtSender::receive(const Packet &ackPkt)
{
    int checkSum = pUtils->calculateCheckSum(ackPkt);
    if (checkSum != ackPkt.checksum)
    {
        pUtils->printPacket("[GBN] Sender received corrupted ACK", ackPkt);
        return;
    }

    // 检查确认号是否在有效范围内
    int ackNum = ackPkt.acknum;
    if (ackNum < 0 || ackNum >= seqSize)
    {
        pUtils->printPacket("[GBN] Sender received invalid ACK number", ackPkt);
        return;
    }

    // 关键修正：正确处理序号回绕
    int relativeAckNum = (ackNum - base + seqSize) % seqSize;
    if (relativeAckNum < 0 || relativeAckNum >= N)
    {
        pUtils->printPacket("[GBN] Sender received ACK outside window", ackPkt);
        return;
    }

    // 标记确认状态
    for (int i = base; i != (ackNum + 1) % seqSize; i = (i + 1) % seqSize)
    {
        int idx = i % seqSize;
        ackStatus[idx] = true;
    }

    // 滑动窗口
    int oldBase = base;
    while (ackStatus[base % seqSize] && base != nextSeqNum)
    {
        ackStatus[base % seqSize] = false;
        base = (base + 1) % seqSize;
    }

    // 更新定时器
    if (base != oldBase)
    {
        pns->stopTimer(SENDER, oldBase);
        if (base != nextSeqNum)
        {
            pns->startTimer(SENDER, Configuration::TIME_OUT, base);
        }
    }

    // 输出窗口状态
    std::cout << "[GBN] Sender window updated: base=" << base
              << ", nextSeqNum=" << nextSeqNum << std::endl;
    printWindowState();
}

// Timeout handler
void GBNRdtSender::timeoutHandler(int seqNum)
{
    // 确保只处理当前base的定时器
    if (seqNum != base)
    {
        std::cout << "[GBN] Ignoring timeout for seqNum=" << seqNum
                  << ", current base=" << base << std::endl;
        return;
    }

    pns->stopTimer(SENDER, seqNum);
    pns->startTimer(SENDER, Configuration::TIME_OUT, seqNum);

    // 只重传base开始的未确认包
    for (int i = base; i != nextSeqNum; i = (i + 1) % seqSize)
    {
        if (!ackStatus[i % seqSize])
        {
            pUtils->printPacket("[GBN] Timeout retransmission", packets[i % seqSize]);
            pns->sendToNetworkLayer(RECEIVER, packets[i % seqSize]);
        }
    }
}

// 返回RdtSender是否处于等待状态
bool GBNRdtSender::getWaitingState()
{
    return (nextSeqNum - base + seqSize) % seqSize >= N;
}

void GBNRdtSender::printWindowState()
{
    std::cout << "windows state: [";

    // 计算从base到nextSeqNum的循环距离
    int dist = (nextSeqNum - base + seqSize) % seqSize;

    for (int i = 0; i < N; i++)
    {
        int currentSeq = (base + i) % seqSize;
        std::string state;

        if (i < dist)
        {
            // 当前序号已发送：检查确认状态
            if (ackStatus[currentSeq])
            {
                state = "ACK"; // 已确认
            }
            else
            {
                state = "SENT"; // 已发送但未确认
            }
        }
        else if (i == dist)
        {
            state = "NEXT"; // 下一个要发送的序号
        }
        else
        {
            state = "UNUSED"; // 尚未使用
        }

        std::cout << currentSeq << "(" << state << ")";
        if (i < N - 1)
        {
            std::cout << ", ";
        }
    }

    std::cout << "], window start seqnum: " << base
              << ", next send seqnum: " << nextSeqNum << std::endl;
}