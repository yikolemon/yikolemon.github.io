---
layout: default
title: Linux运行Galgame通用教程
date: 2026-01-25
---

# Linux运行Galgame通用教程

## 1. 前言

使用steamdeck游玩Galgame有两种选择

1. 使用Windows系统：需要面临重启系统的问题，无法即开即玩，比较麻烦，兼容性强
2. 使用Lutris运行：需要解决兼容性问题，但可以一次解决长久运行，可以集成到SteamDeck的GamingMode中运行（极少部分游戏窗口问题不支持，在RPGMaker游戏中容易出现）

本次介绍Lutris运行Galgame通用教程，市面上比较热门的Galgame大部分都能通过Wine转义运行了，部分需要操作一下

## 2. Lutris添加游戏教程

兼容层：**Proton10 / GE-Proton** 经过测试运行Galgame效果不错，可以根据个人实际体验切换

**使用GE-Proton可能存在GamingMode无法启动的问题，切换Proton兼容层可以解决**

步骤：

1. 安装Lutris

2. 安装ProtonUp-Qt

3. 于ProtonUp-Qt中为Lutris安装更多兼容层

   ![image-20260124231549621](/assets/images/linux运行galgame通用教程/image-20260124231549621.png)

4. 于Lutris中配置游戏

   将windows游戏路径复制到steamdeck中，选择/home/deck下路径较好

   点击添加游戏

   ![image-20260124231716876](/assets/images/linux运行galgame通用教程/image-20260124231716876.png)

   选择使用Wine运行

   ![image-20260124232045909](/assets/images/linux运行galgame通用教程/image-20260124232045909.png)

   选择游戏运行exe和虚拟环境目录

   ![image-20260124232302165](/assets/images/linux运行galgame通用教程/image-20260124232302165.png)

   选择兼容层，选择功能性

   推荐兼容层：**GE-Proton10-28**

   ![image-20260124232459866](/assets/images/linux运行galgame通用教程/image-20260124232459866.png)

   系统选项

   **Locale：部分汉化可能只支持Chinese环境启动，system默认可能不为Chinese环境，如果出现启动错误，可以尝试切换Chinese**

   点击Play运行

   **初次运行可能需要较长时间，是在进行虚拟环境的初始化，请耐心等等，直到出现游戏窗口/错误窗口，或Stop按钮重置为Play**

   ![image-20260124233017237](/assets/images/linux运行galgame通用教程/image-20260124233017237.png)

   成功运行：

   ![image-20260124233703465](/assets/images/linux运行galgame通用教程/image-20260124233703465.png)

## 3. 中文字体问题

部分Galgame官方/汉化组可能使用非自定义字体而是系统字体，Lutris兼容层初始化包含的中文字体很细，需要进行字体更换

例：

![Screenshot_20260124_234309](/assets/images/linux运行galgame通用教程/Screenshot_20260124_234309.png)

打开你Windows电脑上的字体文件夹：

![image-20260124235514497](/assets/images/linux运行galgame通用教程/image-20260124235514497.png)

将Windows字体全部复制到你定义的Wine Prefix下的（Wine Prefix）/drive_c/windows/Fonts路径中

如果你不知道Wine Prefix，请见本文档的：2.Lutris添加游戏教程

![image-20260124235830085](/assets/images/linux运行galgame通用教程/image-20260124235830085.png)

上传成功后，删除你需要修复字体的Galgame的存档

我所演示的游戏的存档位置：

![image-20260124235943591](/assets/images/linux运行galgame通用教程/image-20260124235943591.png)

删除完成后，重新运行游戏，查看中文字体是否正常：

完美运行！

![Screenshot_20260124_235432](/assets/images/linux运行galgame通用教程/Screenshot_20260124_235432.png)