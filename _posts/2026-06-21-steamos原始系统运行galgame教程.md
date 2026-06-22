---
layout: default
title: SteamOS原始系统运行GalGame教程
date: 2026-06-21
---

## 1. 前言 

Q：为什么之前有Lutris的教程，还会有SteamOS

A：Lutris在SteamDeck的兼容性较差，不如SteamOS方便，兼容性强

**本教程经过了Bilibili视频评论区的答疑收集，大部分问题及解决方案都在本文中有排疑和解决方案，如果对你有帮助，可以帮我点点star（虽然项目很烂**

## 2. 安装教程 
视频教程：[SteamDeck原始系统游玩Galgame教程](https://b23.tv/yOH0zka)

工具下载链接：[SteamDeck GalGame环境配置工具](https://github.com/yikolemon/easy-steamdeck-galgame/releases/download/V1.0.0/steamdeck-galgame-release.tar)

## 3. 其他问题

### Ⅰ. OP/ED/游戏内视频无法播放
Proton缺少WMV格式的支持，在不严重影响游戏体验的前提下可以不去修复

如果你需要修复：
1. 使用`ProtonUp-Qt`切换`CachyOS` / `Proton Experimental` / `Proton GE` 
2. 安装wmp(大概率无效)

### Ⅱ. 为什么我的游戏打不开

**解决尝试方案（最好按问题匹配排障）**：

1. 切换`Proton Experimental` / `CachyOS` 兼容层（无法启动/闪退 使用）
2. 切换中文启动参数/日文启动参数（启动后乱码 使用）
3. 切换`Proton7.6` （老Galgame/老破解Galgame闪退 使用）
    - 新版Proton对于内存校验比较严格，老游戏 / 破解程序由于代码问题经常会因为非法访问内存被Proton拦截
4. 对于exe程序注册表，需要切换steam执行程序，运行注册表安装程序后切回游戏本体（需要安装exe注册表使用）
    - 使用protonTricks安装exe注册表无法被游戏环境识别
5. 将游戏目录下的dll文件添加进启动参数中（无法启动/闪退 使用）
    - 添加方式：TODO

### Ⅲ. 游戏无法显示中文

1. 切换中文启动参数
2. 安装游戏所需的系统字体
    - 如果需要使用游戏附带字体，需要使用工具安装
    - 否则，使用工具安装windows系统字体
3. 换一个汉化组的汉化版本（下下策，只限游戏为早期汉化版本使用）

### Ⅲ. 游戏内汉化字体展示不全
**极大概率是由于Proton对于宋体字体的渲染问题**

1. 如果游戏内/外可以切换字体，则切换为其他字体（如黑体）
2. 如果无法切换字体，则尝试切换为其他汉化组汉化版本（很少有汉化组会使用宋体作为游戏字体，部分早期汉化版会这样）

## 4.后言

**大部分的Galgame都可以通过以上方案及排障正常游玩（无法播放OP/ED/动画不影响游戏的前体下），部分新游戏由于厂商使用的自制的游戏引擎，在有游戏内有大量的动态元素，无法正常游玩，暂时没有找到合适的解决方案**

**对于动画/OP/ED的播放问题，如果你有好的解决方案，可以在视频评论区留意，造福更多玩家，感谢**


