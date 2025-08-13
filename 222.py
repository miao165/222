import csv
import os
import time
from datetime import date
from io import BytesIO
import re
import requests
from PIL import Image
from PyPDF2 import PdfMerger
from loguru import logger
from playwright.sync_api import sync_playwright
import faulthandler
faulthandler.enable()

def get_link_from_csv(date_str: str) -> str:
    csv_file_path = '2025-08-11 17_02_52.csv'  # 确保这是正确的路径
    try:
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['时间time'].strip() == date_str.strip():    # 确保格式匹配
                    logger.info(f"Found link for {date_str}: {row['链接url']}")
                    return row['链接url']
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")
    logger.warning(f"No link found for {date_str}")
    return None

def generate_pdf(report_dir: str, target_dates: list):
    def _merge_pdf(meta_root: str, date_str: str):
        pdfs = [os.path.join(meta_root, _f) for _f in os.listdir(meta_root) if _f.endswith('.pdf')]
        pdfs.sort()
        pdf_merger = PdfMerger()

        output_path = os.path.join(report_dir, date_str, f'{date_str}.pdf')  # 提前定义

        for _pdf in pdfs:
            pdf_merger.append(_pdf)
        if pdfs:
            with open(output_path, 'wb') as output:
                pdf_merger.write(output)
            logger.info(f"[merge_pdf] PDF saved: {output_path}")
        else:
            logger.warning(f"[merge_pdf] No PDFs to merge for {date_str}")
        pdf_merger.close()

    url_pattern = re.compile(r'^https?://')  # 简单URL验证

    logger.info(f'[generate_pdf] target dates: {target_dates}')
    for _target_date in target_dates:
        date_str = _target_date.strftime('%Y-%m-%d')
        rootdir = os.path.join(report_dir, date_str)
        meta_root = os.path.join(rootdir, 'metadata')
        os.makedirs(meta_root, exist_ok=True)

        link = get_link_from_csv(date_str)  # 从 CSV 文件中获取链接

        if link:
            with sync_playwright() as playwright:
                logger.info(f"[goto] Opening link for {date_str}")
                browser = playwright.chromium.launch(headless=False)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                page.goto(link, wait_until="domcontentloaded")

                # 模拟人类滚动 + 等待图片渲染
                for _ in range(5):
                    page.mouse.wheel(0, 800)
                    time.sleep(1)

                # 等待 DOM 确认所有图片加载
                page.wait_for_selector("img", state="attached", timeout=10000)

                # 获取所有图片（包括懒加载）
                img_objs = page.locator("img").all()  # windows len != 0, linux len == 0
                img_urls = []
                for _img_obj in img_objs:
                    url = _img_obj.get_attribute("data-src") or _img_obj.get_attribute("src")
                    if url and url != 'undefined' and url_pattern.match(url):
                        img_urls.append(url)
                    else:
                        logger.debug(f"[skip_url] Invalid or undefined img url skipped: {url}")

                logger.info(f"[selector] Found {len(img_urls)} images for {date_str}")

                if not img_urls:
                    logger.warning(f"[skip] No images found for {date_str}, skipping PDF generation.")
                else:
                    for _idx, _img_url in enumerate(img_urls):
                        try:
                            response = requests.get(_img_url, timeout=15)
                            response.raise_for_status()
                            img = Image.open(BytesIO(response.content))
                            if img.mode == 'RGBA':
                                img = img.convert('RGB')
                            if img.width > 1000 and img.height > 1500:
                                img.save(os.path.join(meta_root, f'{_idx}.jpg'))
                                img.save(os.path.join(meta_root, f'{_idx}.pdf'))
                        except Exception as e:
                            logger.error(f"[error] Failed to download {_img_url}: {e}")

                    _merge_pdf(meta_root, date_str)


                    browser.close()
            time.sleep(5)
        else:
            logger.warning(f'No link found for date {date_str}')

if __name__ == '__main__':
    report_dir = 'report'  # 替换为你的报告目录路径
    target_dates = [date(2025, 8, 7), date(2025, 8, 8), date(2025, 8, 9)]  # 替换为你需要处理的日期列表
    generate_pdf(report_dir, target_dates)