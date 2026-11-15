"""Generate the shared QR after an HTTPS deployment: pip install 'qrcode==8.2'."""
import argparse
from urllib.parse import urlsplit
import qrcode
p=argparse.ArgumentParser();p.add_argument('url');p.add_argument('--output',default='forum-qr.svg');a=p.parse_args()
if urlsplit(a.url).scheme!='https' or not urlsplit(a.url).hostname: p.error('Use the public HTTPS application URL')
from qrcode.image.svg import SvgPathImage
qrcode.make(a.url,image_factory=SvgPathImage,border=4).save(a.output)
print(a.output)
