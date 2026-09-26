#include "SRRdtReceiver.h"
#include "Global.h"
#include "Tool.h"
#include <iostream>
#include <cstring>

SRRdtReceiver::SRRdtReceiver()
    : expectedSeqNum(0),
      seqNumBits(3),
      windowSize(4)
{
    modulus = 1 << seqNumBits;

    pkts.resize(windowSize);
    rcvdStatus.resize(windowSize, false);

    std::cout << "SR协议接收方初始化完成" << std::endl;
    std::cout << "序号位数: " << seqNumBits
              << ", 窗口大小: " << windowSize
              << ", 序号范围: 0-" << (modulus - 1) << std::endl;
}

SRRdtReceiver::~SRRdtReceiver()
{
    // 无需显式清理
}

bool SRRdtReceiver::inWindow(int seqNum) const
{
    int end = (expectedSeqNum + windowSize - 1) % modulus;
    if (expectedSeqNum <= end)
        return seqNum >= expectedSeqNum && seqNum <= end;
    else
        return seqNum >= expectedSeqNum || seqNum <= end;
}

void SRRdtReceiver::sendAck(int seqNum)
{
    Packet ackPkt;
    ackPkt.seqnum = -1;
    ackPkt.acknum = seqNum;
    for (int i = 0; i < Configuration::PAYLOAD_SIZE; i++)
        ackPkt.payload[i] = '.';
    ackPkt.checksum = pUtils->calculateCheckSum(ackPkt);

    pUtils->printPacket("接收方发送确认报文", ackPkt);
    pns->sendToNetworkLayer(SENDER, ackPkt);

    ackCache[seqNum] = ackPkt;
}

void SRRdtReceiver::receive(const Packet &packet)
{
    int checkSum = pUtils->calculateCheckSum(packet);
    if (checkSum != packet.checksum)
    {
        pUtils->printPacket("接收方收到损坏的报文", packet);
        return;
    }

    int seqNum = packet.seqnum;

    // 如果在当前接收窗口内
    if (inWindow(seqNum))
    {
        int index = seqNum % windowSize;

        if (!rcvdStatus[index])
        {
            pkts[index] = packet;
            rcvdStatus[index] = true;
            pUtils->printPacket("接收方缓存分组", packet);
        }
        else
        {
            // 重复分组
            pUtils->printPacket("接收方收到重复分组，重新发送ACK", packet);
        }

        // 无论新旧分组，都要发送 ACK
        sendAck(seqNum);

        // 如果正好是期望序号，则尝试交付应用层
        if (seqNum == expectedSeqNum)
        {
            deliverToApplication();
        }
    }
    else
    {
        // 不在窗口内：可能是已经交付过的旧分组
        // 如果缓存中有旧ACK，则重发 ACK
        if (ackCache.count(seqNum))
        {
            pUtils->printPacket("接收方收到过期分组，重发上次ACK", packet);
            pns->sendToNetworkLayer(SENDER, ackCache[seqNum]);
        }
        else
        {
            pUtils->printPacket("接收方收到窗口外分组，忽略", packet);
        }
    }

    printWindowState();
}

void SRRdtReceiver::deliverToApplication()
{
    while (rcvdStatus[expectedSeqNum % windowSize])
    {
        int index = expectedSeqNum % windowSize;

        // 交付数据
        Message msg;
        memcpy(msg.data, pkts[index].payload, sizeof(pkts[index].payload));
        pns->delivertoAppLayer(RECEIVER, msg);

        // 标记该位置空
        rcvdStatus[index] = false;

        // 更新期望序号
        expectedSeqNum = (expectedSeqNum + 1) % modulus;
    }

    printWindowState();
}

void SRRdtReceiver::printWindowState() const
{
    std::cout << "接收窗口状态: [";
    for (int i = 0; i < windowSize; i++)
    {
        int seq = (expectedSeqNum + i) % modulus;
        std::cout << seq;
        if (rcvdStatus[seq % windowSize])
            std::cout << "(RCVD)";
        else
            std::cout << "(EMPTY)";
        if (i < windowSize - 1)
            std::cout << ", ";
    }
    std::cout << "], 期望接收序号: " << expectedSeqNum << std::endl;
}
