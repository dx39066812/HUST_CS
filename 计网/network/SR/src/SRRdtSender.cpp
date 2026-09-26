#include "SRRdtSender.h"
#include "Global.h"
#include "Tool.h"
#include <iostream>
#include <cstring>
#include <algorithm>

SRRdtSender::SRRdtSender() : nextSeqNum(0),
                             baseSeqNum(0),
                             seqNumBits(3),
                             windowSize(4)
{
    modulus = 1 << seqNumBits;

    // 初始化窗口数据结构
    pkts.resize(windowSize);
    ackStatus.resize(windowSize, false);
    timerStatus.resize(windowSize, false);

    std::cout << "SR协议发送方初始化完成" << std::endl;
    std::cout << "序号位数: " << seqNumBits << ", 窗口大小: " << windowSize << std::endl;
    std::cout << "序号范围: 0-" << (modulus - 1) << std::endl;
}

SRRdtSender::~SRRdtSender()
{
    // 停止所有活跃的定时器
    for (int i = 0; i < windowSize; i++)
    {
        if (timerStatus[i])
        {
            int seqNum = (baseSeqNum + i) % modulus;
            pns->stopTimer(SENDER, seqNum);
        }
    }
}

bool SRRdtSender::getWaitingState()
{
    int relativeNextSeq = (nextSeqNum - baseSeqNum + modulus) % modulus;
    return relativeNextSeq >= windowSize;
}

bool SRRdtSender::send(const Message &message)
{
    if (getWaitingState())
    {
        std::cout << "发送窗口已满，拒绝应用层数据" << std::endl;
        return false;
    }

    int index = (nextSeqNum - baseSeqNum + modulus) % modulus;

    // 构造数据包
    Packet pkt;
    pkt.seqnum = nextSeqNum;
    pkt.acknum = -1;
    memcpy(pkt.payload, message.data, sizeof(message.data));
    pkt.checksum = 0;
    pkt.checksum = pUtils->calculateCheckSum(pkt);

    // 保存数据包
    pkts[index] = pkt;
    ackStatus[index] = false;

    // 发送数据包
    pUtils->printPacket("发送方发送数据报文", pkt);
    pns->sendToNetworkLayer(RECEIVER, pkt);

    // 启动该分组的定时器
    if (!timerStatus[index])
    {
        pns->startTimer(SENDER, Configuration::TIME_OUT, nextSeqNum);
        timerStatus[index] = true;
        std::cout << "启动分组 " << nextSeqNum << " 的定时器" << std::endl;
    }

    // 更新下一个序号
    nextSeqNum = (nextSeqNum + 1) % modulus;

    printWindowState();
    return true;
}

void SRRdtSender::receive(const Packet &ackPkt)
{
    int checkSum = pUtils->calculateCheckSum(ackPkt);

    if (checkSum != ackPkt.checksum)
    {
        pUtils->printPacket("发送方收到错误的确认报文", ackPkt);
        return;
    }

    int ackNum = ackPkt.acknum;

    // 检查确认号是否在当前窗口内
    if (!inWindow(ackNum))
    {
        std::cout << "确认序号 " << ackNum << " 不在当前窗口内，忽略" << std::endl;
        return;
    }

    // 计算相对索引
    int index = (ackNum - baseSeqNum + modulus) % modulus;

    // 确保索引在窗口范围内
    if (index >= windowSize)
    {
        std::cout << "计算出的索引 " << index << " 超出窗口范围，忽略确认" << std::endl;
        return;
    }

    pUtils->printPacket("发送方收到确认包", ackPkt);
    // 处理确认
    ackStatus[index] = true;

    // 停止定时器
    if (timerStatus[index])
    {
        pns->stopTimer(SENDER, ackNum);
        timerStatus[index] = false;
        std::cout << "停止分组 " << ackNum << " 的定时器" << std::endl;
    }

    // 如果确认的是窗口起始分组，尝试滑动窗口
    if (ackNum == baseSeqNum)
    {
        slideWindow();
    }

    printWindowState();
}

void SRRdtSender::slideWindow()
{
    int slideCount = 0;

    while (slideCount < windowSize && ackStatus[slideCount])
    {
        slideCount++;
    }

    if (slideCount > 0)
    {
        for (int i = 0; i < windowSize - slideCount; i++)
        {
            pkts[i] = pkts[i + slideCount];
            ackStatus[i] = ackStatus[i + slideCount];
            timerStatus[i] = timerStatus[i + slideCount];
        }

        for (int i = windowSize - slideCount; i < windowSize; i++)
        {
            ackStatus[i] = false;
            timerStatus[i] = false;
        }

        baseSeqNum = (baseSeqNum + slideCount) % modulus;
        std::cout << "窗口滑动至起始序号: " << baseSeqNum << std::endl;
    }
    printWindowState();
}

void SRRdtSender::timeoutHandler(int seqNum)
{
    if (!inWindow(seqNum))
    {
        std::cout << "超时分组 " << seqNum << " 不在当前窗口内" << std::endl;
        return;
    }

    int index = (seqNum - baseSeqNum + modulus) % modulus;

    // 重传超时的分组
    pUtils->printPacket("发送方定时器超时，重传数据报文", pkts[index]);
    pns->sendToNetworkLayer(RECEIVER, pkts[index]);

    // 重启定时器
    pns->stopTimer(SENDER, seqNum);
    pns->startTimer(SENDER, Configuration::TIME_OUT, seqNum);
    timerStatus[index] = true;

    std::cout << "分组 " << seqNum << " 超时重传" << std::endl;
}

bool SRRdtSender::inWindow(int seqNum) const
{
    if (baseSeqNum <= (baseSeqNum + windowSize - 1) % modulus)
    {
        // 窗口没有跨越序号边界
        return seqNum >= baseSeqNum && seqNum < baseSeqNum + windowSize;
    }
    else
    {
        // 窗口跨越序号边界
        return seqNum >= baseSeqNum || seqNum < (baseSeqNum + windowSize) % modulus;
    }
}

void SRRdtSender::printWindowState() const
{
    std::cout << "发送窗口状态: [";
    for (int i = 0; i < windowSize; i++)
    {
        int seq = (baseSeqNum + i) % modulus;
        std::cout << seq;
        if (ackStatus[i])
        {
            std::cout << "(ACK)";
        }
        else if (timerStatus[i])
        {
            std::cout << "(SENT)";
        }
        else
        {
            std::cout << "(EMPTY)";
        }

        if (i < windowSize - 1)
        {
            std::cout << ", ";
        }
    }
    std::cout << "], 窗口起始序号: " << baseSeqNum << ", 下一个发送序号: " << nextSeqNum << std::endl;
}