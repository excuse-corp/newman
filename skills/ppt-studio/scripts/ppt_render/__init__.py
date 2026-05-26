"""ppt_render — dual-render PPT engine.

Single layout logic, two outputs:
  layout(data, theme) -> list[Element]
    -> to_html(elements)  -> HTML string  (preview)
    -> to_pptx(elements)  -> python-pptx slide  (export)
"""
