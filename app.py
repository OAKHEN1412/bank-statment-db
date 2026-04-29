import os
import time
import uuid
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify, send_file)
import io

from db import init_db, save_transactions, file_already_imported, get_transactions, get_banks, get_summary, get_import_logs, delete_bank, delete_file
from parsers import parse_pdf
from checker import process_excel, export_excel
from updater import check_for_update, apply_update, get_config as get_update_config, save_config as save_update_config, update_version_number

# Store last check results in memory (single-user local app)
_check_cache = {'results': None, 'summary': None, 'filename': ''}
# Cache update check for 1 hour to avoid GitHub rate-limit
_update_cache = {'result': None, 'checked_at': 0}

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.context_processor
def inject_version():
    try:
        return {'app_version': get_update_config().get('version', '1.0.0')}
    except Exception:
        return {'app_version': '1.0.0'}

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BANKS = ['BBL', 'KBANK', 'KTB', 'SCB', 'TTB']


@app.route('/')
def index():
    summary = get_summary()
    logs = get_import_logs()
    return render_template('index.html', banks=BANKS, summary=summary, logs=logs)


@app.route('/upload', methods=['POST'])
def upload():
    bank = request.form.get('bank', '').upper()
    files = request.files.getlist('pdf_files')

    if not bank or bank not in BANKS:
        flash('กรุณาเลือกธนาคาร', 'danger')
        return redirect(url_for('index'))
    if not files or all(f.filename == '' for f in files):
        flash('กรุณาเลือกไฟล์ PDF', 'danger')
        return redirect(url_for('index'))

    ok_count = 0
    total_rows = 0
    for f in files:
        if not f or not f.filename:
            continue
        if not f.filename.lower().endswith('.pdf'):
            flash(f'ข้ามไฟล์ "{f.filename}" — ไม่ใช่ .pdf', 'warning')
            continue

        safe_name = f'{uuid.uuid4().hex}.pdf'
        tmp_path = os.path.join(UPLOAD_FOLDER, safe_name)
        f.save(tmp_path)
        original_name = f.filename
        try:
            # Check duplicate file
            if file_already_imported(bank, original_name):
                flash(
                    f'ข้ามไฟล์ "{original_name}" — เคย import แล้ว '
                    f'(ถ้าต้องการ import ใหม่ ให้ลบไฟล์เดิมออกก่อน)',
                    'warning'
                )
                continue

            rows = parse_pdf(bank, tmp_path)
            if rows:
                count, skipped = save_transactions(bank, rows, original_name)
                total_rows += count
                ok_count += 1
                if skipped:
                    flash(f'"{original_name}": บันทึก {count:,} รายการ (ข้ามซ้ำ {skipped:,} รายการ)', 'info')
            else:
                flash(
                    f'ไม่พบรายการในไฟล์ "{original_name}" '
                    f'(อาจเป็น PDF ภาพสแกนที่ไม่รองรับ)',
                    'warning'
                )
        except Exception as e:
            flash(f'เกิดข้อผิดพลาด ({original_name}): {e}', 'danger')
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    if ok_count:
        flash(f'บันทึกสำเร็จ {ok_count} ไฟล์ รวม {total_rows:,} รายการ ({bank})', 'success')

    return redirect(url_for('index'))


@app.route('/view')
def view():
    bank = request.args.get('bank', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = max(1, int(request.args.get('page', 1)))
    per_page = 200

    rows, total = get_transactions(bank, date_from, date_to, page, per_page)
    banks = get_banks()
    total_pages = max(1, -(-total // per_page))  # ceiling division

    return render_template(
        'view.html',
        transactions=rows,
        banks=banks,
        bank=bank,
        date_from=date_from,
        date_to=date_to,
        page=page,
        total=total,
        total_pages=total_pages,
        per_page=per_page,
    )


@app.route('/api/transactions')
def api_transactions():
    bank = request.args.get('bank', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    rows, total = get_transactions(bank, date_from, date_to)
    return jsonify({'total': total, 'data': rows})


@app.route('/delete_bank', methods=['POST'])
def delete_bank_route():
    bank = request.form.get('bank', '')
    if bank in BANKS:
        delete_bank(bank)
        flash(f'ลบข้อมูลธนาคาร {bank} ทั้งหมดเรียบร้อย', 'success')
    return redirect(url_for('index'))


@app.route('/delete_file', methods=['POST'])
def delete_file_route():
    bank = request.form.get('bank', '')
    filename = request.form.get('filename', '')
    if bank and filename:
        delete_file(bank, filename)
        flash(f'ลบไฟล์ {filename} ของธนาคาร {bank} เรียบร้อย', 'success')
    return redirect(url_for('index'))


# ─── Check Statement ───────────────────────────────────────────────────────────

@app.route('/check', methods=['GET', 'POST'])
def check():
    results = None
    summary = None
    filename = ''
    filter_status = request.args.get('filter', 'all')

    if request.method == 'POST':
        f = request.files.get('xlsx_file')
        if not f or not f.filename:
            flash('กรุณาเลือกไฟล์ Excel (.xlsx)', 'danger')
            return redirect(url_for('check'))
        if not f.filename.lower().endswith(('.xlsx', '.xls')):
            flash('รองรับเฉพาะไฟล์ .xlsx / .xls', 'danger')
            return redirect(url_for('check'))

        filename = f.filename
        try:
            stream = io.BytesIO(f.read())
            results, summary = process_excel(stream)
            _check_cache['results'] = results
            _check_cache['summary'] = summary
            _check_cache['filename'] = filename
        except Exception as e:
            flash(f'เกิดข้อผิดพลาด: {e}', 'danger')
            return redirect(url_for('check'))
    else:
        # Restore last results if available
        results = _check_cache.get('results')
        summary = _check_cache.get('summary')
        filename = _check_cache.get('filename', '')

    # Apply filter
    filtered = results
    if results and filter_status != 'all':
        filtered = [r for r in results if r['status'] == filter_status]

    return render_template(
        'check.html',
        results=filtered,
        summary=summary,
        filename=filename,
        filter_status=filter_status,
    )


@app.route('/check/export')
def check_export():
    results = _check_cache.get('results')
    if not results:
        flash('ไม่มีข้อมูลให้ export กรุณา upload ไฟล์ก่อน', 'warning')
        return redirect(url_for('check'))
    data = export_excel(results)
    return send_file(
        io.BytesIO(data),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='check_results.xlsx',
    )


@app.route('/check/clear', methods=['POST'])
def check_clear():
    _check_cache['results'] = None
    _check_cache['summary'] = None
    _check_cache['filename'] = ''
    return redirect(url_for('check'))


# ─── Self-Update ──────────────────────────────────────────────────────────────

@app.route('/update')
def update_page():
    config = get_update_config()
    return render_template('update.html', config=config)


@app.route('/update/check')
def update_check():
    force = request.args.get('force') == '1'
    now = time.time()
    if not force and _update_cache['result'] and (now - _update_cache['checked_at']) < 3600:
        return jsonify(_update_cache['result'])
    result = check_for_update()
    _update_cache['result'] = result
    _update_cache['checked_at'] = now
    return jsonify(result)


@app.route('/update/apply', methods=['POST'])
def update_apply():
    data = request.get_json()
    download_url = (data or {}).get('download_url', '')
    latest_version = (data or {}).get('latest_version', '')
    if not download_url:
        return jsonify({'success': False, 'message': 'No download URL'})
    ok, msg = apply_update(download_url)
    if ok and latest_version:
        update_version_number(latest_version)
        _update_cache['result'] = None  # invalidate cache
    return jsonify({'success': ok, 'message': msg})


@app.route('/update/save-config', methods=['POST'])
def update_save_config():
    data = request.get_json()
    repo = (data or {}).get('github_repo', '').strip()
    save_update_config(repo)
    _update_cache['result'] = None  # invalidate cache after repo change
    return jsonify({'success': True})


if __name__ == '__main__':
    init_db()
    print('Starting Bank Statement Web App on http://127.0.0.1:5000')
    app.run(debug=False, host='127.0.0.1', port=5000)
