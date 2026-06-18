---
layout: default
---

<section class="home-hero" aria-labelledby="site-intro-title">
  <p class="eyebrow">Personal writing desk</p>
  <h1 id="site-intro-title">Yikolemon's Articles</h1>
  <p class="lede">技术、游戏与日常实验的个人记录。</p>
</section>

<section class="article-thread" aria-label="Articles">
  {% for post in site.posts %}
  <article class="post-card">
    <div class="post-header">
      <div>
        <p class="post-kicker">Article {{ forloop.index | prepend: '0' | slice: -2, 2 }}</p>
        <h2 class="post-title"><a href="{{ post.url | relative_url }}">{{ post.title }}</a></h2>
      </div>
      <time class="post-meta" datetime="{{ post.date | date_to_xmlschema }}">{{ post.date | date: "%Y-%m-%d" }}</time>
    </div>
  </article>
  {% endfor %}
</section>
