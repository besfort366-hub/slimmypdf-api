from flask import Flask, request, make_response, jsonify
from flask_cors import CORS
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from PIL import Image
import io, os

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

                        # Always resize and recompress for speed
                        if max(img.width, img.height) > MAX_DIM:
                            ratio = MAX_DIM / max(img.width, img.height)
                            new_w = int(img.width * ratio)
                            new_h = int(img.height * ratio)
                            img = img.resize((new_w, new_h), Image.BILINEAR)  # BILINEAR is faster than LANCZOS

                        buf = io.BytesIO()
                        img.convert('RGB').save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=False)  # optimize=False is faster
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
