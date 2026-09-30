import html


class Plugin:
    """DevLauncher 示例插件：读取配置并在详情页渲染自定义内容区。"""

    def on_load(self, ctx):
        cfg = ctx.get_config()
        greeting = html.escape(str(cfg.get("greeting", "你好")))
        max_items = cfg.get("max_items", 5)
        anim = "开启" if cfg.get("enabled_anim", True) else "关闭"
        ctx.register_content(
            f"<div class='plugin-content'>"
            f"<h4>{greeting}，欢迎使用示例插件</h4>"
            f"<p>动画：{anim} · 最大条目：{max_items}</p>"
            f"</div>"
        )
        ctx.logger.info("hello-sample on_load 完成")
