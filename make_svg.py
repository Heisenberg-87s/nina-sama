import base64
import os

png_path = os.path.join('nina-ui', 'public', 'icons.png')
svg_path = os.path.join('nina-ui', 'public', 'icons.svg')

with open(png_path, 'rb') as f:
    encoded = base64.b64encode(f.read()).decode('utf-8')

svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 512 512">
  <image href="data:image/png;base64,{encoded}" width="100%" height="100%" />
</svg>"""

with open(svg_path, 'w') as f:
    f.write(svg_content)

print(f"Created {svg_path}")
