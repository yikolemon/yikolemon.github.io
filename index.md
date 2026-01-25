---
layout: default
---

{% for post in site.posts %}
<div class="post-card">
  <div class="post-header">
    <h2 class="post-title"><a href="{{ post.url }}">{{ post.title }}</a></h2>
    <div class="post-meta">{{ post.date | date: "%Y-%m-%d" }}</div>
  </div>
</div>
{% endfor %}

<style>
/* 全局样式重置 */
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  background-color: #f8fafc;
  color: #2d3748;
  line-height: 1.6;
}

/* 主内容区域 */
.main-content {
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 20px;
}

/* 文章卡片 */
.post-card {
  background: white;
  border-radius: 12px;
  padding: 28px;
  margin-bottom: 24px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;
  border: 1px solid #e2e8f0;
  text-align: left;
}

/* 卡片悬停效果 */
.post-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  border-color: #cbd5e0;
}

/* 文章头部 */
.post-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: nowrap;
  gap: 16px;
  width: 100%;
}

/* 文章标题 */
.post-title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  color: #2d3748;
  flex: 1;
  min-width: 0;
  text-align: left;
}

/* 标题链接 */
.post-title a {
  color: inherit;
  text-decoration: none;
  transition: color 0.3s ease;
  display: inline-block;
  line-height: 1.3;
  vertical-align: middle;
}

/* 标题链接悬停效果 */
.post-title a:hover {
  color: #3182ce;
  text-decoration: none;
}

/* 文章元信息 */
.post-meta {
  color: #718096;
  font-size: 14px;
  font-weight: 500;
  background-color: #f7fafc;
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 0;
  vertical-align: middle;
}

/* 响应式设计 */
@media (max-width: 640px) {
  .post-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .post-title {
    font-size: 22px;
  }
  
  .post-card {
    padding: 20px;
  }
}
</style>
