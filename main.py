from flask import Flask, request, make_response, jsonify, send_file
from flask_cors import CORS
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from PIL import Image
import io, os, zipfile

app = Flask(__name__)
CORS(app, origins=['https://slimmypdf.com', 'https://www.slimmypdf.com', 'http://slimmypdf.com', 'http://localhost', 'http://127.0.0.1'])

Image.MAX_IMAGE_PIXELS = None

QUALITY_SETTINGS = {
    'low':    {'max_dim': 5000, 'jpeg_quality': 88},
    'medium': {'max_dim': 3500, 'jpeg_quality': 82},
    'high':   {'max_dim': 2500, 'jpeg_quality': 70},
}

@app.route('/')
def index():
    return jsonify({'status': 'SlimMyPDF API running'})

@app.route('/compress', methods=['POST'])
def compress():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    quality = request.form.get('quality', 'medium')
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a PDF file'}), 400
    if quality not in QUALITY_SETTINGS:
        quality = 'medium'
    settings = QUALITY_SETTINGS[quality]
    MAX_DIM = settings['max_dim']
    JPEG_QUALITY = settings['jpeg_quality']
    try:
        pdf_bytes = file.read()
        original_size = len(pdf_bytes)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            resources = page.get('/Resources', {})
            xobj_dict = resources.get('/XObject', {})
            for key in xobj_dict:
                obj = xobj_dict[key]
                if obj.get('/Subtype') == '/Image':
                    try:
                        w = int(obj['/Width'])
                        h = int(obj['/Height'])
                        raw = obj.get_data()
                        try:
                            img = Image.open(io.BytesIO(raw))
                            img.load()
                        except:
                            cs = obj.get('/ColorSpace', '/DeviceRGB')
                            mode = 'RGB' if cs == '/DeviceRGB' else 'L'
                            img = Image.frombytes(mode, (w, h), raw)
                        if max(img.width, img.height) > MAX_DIM:
                            ratio = MAX_DIM / max(img.width, img.height)
                            new_w = int(img.width * ratio)
                            new_h = int(img.height * ratio)
                            img = img.resize((new_w, new_h), Image.BILINEAR)
                        buf = io.BytesIO()
                        img.convert('RGB').save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=False)
                        buf.seek(0)
                        new_data = buf.read()
                        obj._data = new_data
                        obj[NameObject('/Filter')] = NameObject('/DCTDecode')
                        obj[NameObject('/Width')] = NumberObject(img.width)
                        obj[NameObject('/Height')] = NumberObject(img.height)
                        obj[NameObject('/Length')] = NumberObject(len(new_data))
                        obj[NameObject('/ColorSpace')] = NameObject('/DeviceRGB')
                        obj[NameObject('/BitsPerComponent')] = NumberObject(8)
                    except Exception:
                        pass
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        out.seek(0)
        compressed_bytes = out.read()
        compressed_size = len(compressed_bytes)
        original_name = file.filename.replace('.pdf', '_slimmed.pdf')
        savings = round((1 - compressed_size / original_size) * 100, 1)
        response = make_response(compressed_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{original_name}"'
        response.headers['X-Original-Size'] = str(original_size)
        response.headers['X-Compressed-Size'] = str(compressed_size)
        response.headers['X-Savings-Percent'] = str(savings)
        response.headers['Access-Control-Expose-Headers'] = 'X-Original-Size, X-Compressed-Size, X-Savings-Percent'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/merge', methods=['POST'])
def merge():
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        return jsonify({'error': 'Please upload at least 2 PDF files.'}), 400
    try:
        writer = PdfWriter()
        total_pages = 0
        for f in files:
            f.seek(0)
            reader = PdfReader(f)
            for page in reader.pages:
                writer.add_page(page)
            total_pages += len(reader.pages)
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        merged_bytes = output.read()
        merged_size = len(merged_bytes)
        response = make_response(merged_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename="merged.pdf"'
        response.headers['X-Merged-Size'] = str(merged_size)
        response.headers['X-Page-Count'] = str(total_pages)
        response.headers['Access-Control-Expose-Headers'] = 'X-Merged-Size, X-Page-Count'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/split', methods=['POST'])
def split():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    mode = request.form.get('mode', 'all')
    pages_param = request.form.get('pages', '')
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a PDF file'}), 400
    try:
        pdf_bytes = file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)

        def parse_pages(param, total):
            pages = set()
            for part in param.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = part.split('-', 1)
                    start = max(1, int(start.strip()))
                    end = min(total, int(end.strip()))
                    pages.update(range(start, end + 1))
                elif part.isdigit():
                    p = int(part)
                    if 1 <= p <= total:
                        pages.add(p)
            return sorted(pages)

        if mode == 'range' and pages_param:
            page_nums = parse_pages(pages_param, total_pages)
            if not page_nums:
                return jsonify({'error': 'No valid pages found in range.'}), 400
            writer = PdfWriter()
            for p in page_nums:
                writer.add_page(reader.pages[p - 1])
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            result_bytes = out.read()
            response = make_response(result_bytes)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = 'attachment; filename="extracted_pages.pdf"'
            response.headers['X-Pages-Extracted'] = str(len(page_nums))
            response.headers['X-Files-Created'] = '1'
            response.headers['Access-Control-Expose-Headers'] = 'X-Pages-Extracted, X-Files-Created'
            return response
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(reader.pages):
                    writer = PdfWriter()
                    writer.add_page(page)
                    page_buf = io.BytesIO()
                    writer.write(page_buf)
                    page_buf.seek(0)
                    zf.writestr(f'page_{i + 1}.pdf', page_buf.read())
            zip_buffer.seek(0)
            result_bytes = zip_buffer.read()
            response = make_response(result_bytes)
            response.headers['Content-Type'] = 'application/zip'
            response.headers['Content-Disposition'] = 'attachment; filename="split_pages.zip"'
            response.headers['X-Pages-Extracted'] = str(total_pages)
            response.headers['X-Files-Created'] = str(total_pages)
            response.headers['Access-Control-Expose-Headers'] = 'X-Pages-Extracted, X-Files-Created'
            return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
