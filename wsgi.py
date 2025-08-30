#!/usr/bin/env python

import json
import os, io, zipfile
import logging
from functools import wraps
import urllib.request
import base64
import subprocess

from PyPDF2 import PdfFileReader, PdfFileWriter
from flask import Flask, request, make_response, abort
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

font_config = FontConfiguration()

app = Flask('pdf')


def authenticate(f):
    @wraps(f)
    def checkauth(*args, **kwargs):
        if 'X_API_KEY' not in request.headers or os.environ.get('X_API_KEY') == request.headers['X_API_KEY']:
            return f(*args, **kwargs)
        else:
            abort(401)

    return checkauth


def auth():
    if app.config.from_envvar('X_API_KEY') == request.headers['X_API_KEY']:
        return True
    else:
        abort(401)


@app.route('/health')
def index():
    return 'ok'


@app.before_first_request
def setup_logging():
    logging.addLevelName(logging.DEBUG, "\033[1;36m%s\033[1;0m" % logging.getLevelName(logging.DEBUG))
    logging.addLevelName(logging.INFO, "\033[1;32m%s\033[1;0m" % logging.getLevelName(logging.INFO))
    logging.addLevelName(logging.WARNING, "\033[1;33m%s\033[1;0m" % logging.getLevelName(logging.WARNING))
    logging.addLevelName(logging.ERROR, "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.ERROR))

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s '
        '[in %(pathname)s:%(lineno)d]'
    ))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.DEBUG)


@app.route('/')
def home():
    return '''
            <h1>PDF Generator</h1>
            <p>The following endpoints are available:</p>
            <ul>
                <li>POST to <code>/pdf?filename=myfile.pdf</code>. The body should
                    contain html or a JSON list of html strings and css strings: { "html": base64_encoded(html), "css": base64_encoded(css) }</li>
                <li>POST to <code>/zip?filename=myfile.pdf</code>. The body should
                    contain html or a JSON list of html strings and css strings: { "html": base64_encoded(html), "css": base64_encoded(css) }</li>
                <li>POST to <code>/multiple?filename=myfile.pdf</code>. The body
                    should contain a JSON list of html strings. They will each
                    be rendered and combined into a single pdf</li>
            </ul>
        '''


@app.route('/pdf', methods=['POST'])
@authenticate
def generate():
    name = request.args.get('filename', 'unnamed.pdf')
    app.logger.info('POST  /pdf?filename=%s' % name)
    app.logger.info('Content-Type %s' % request.headers['Content-Type'])

    if request.headers['Content-Type'] == 'application/json':
        data = json.loads(request.data.decode('utf-8'))

        html = HTML(string=base64.b64decode(data['html']))
        css = CSS(string=base64.b64decode(data['css']), font_config=font_config)
        user_password = data.get('user_password')
        owner_password = data.get('owner_password')

        pdf = html.write_pdf(stylesheets=[css], font_config=font_config)

        if user_password:
            reader = PdfFileReader(io.BytesIO(pdf))
            writer = PdfFileWriter()
            writer.appendPagesFromReader(reader)
            writer.encrypt(user_password, owner_pwd=owner_password)

            with io.BytesIO() as f:
                writer.write(f)
                pdf = f.getvalue()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline;filename=%s' % name
    app.logger.info(' ==> POST  /pdf?filename=%s  ok' % name)
    return response

# create route to accept input as xlsx file and use unoconv to convert to pdf
@app.route('/xlsx', methods=['POST'])
@authenticate
def xlsx():
    name = request.args.get('filename', 'unnamed.pdf')
    app.logger.info('POST  /xlsx?filename=%s' % name)
    app.logger.info('Content-Type %s' % request.headers['Content-Type'])

    if request.headers['Content-Type'] == 'application/json':
        data = json.loads(request.data.decode('utf-8'))

        # write xlsx file to disk
        with open('input.xlsx', 'wb') as f:
            f.write(base64.b64decode(data['xlsx']))

        user_password = data.get('user_password')

        # convert xlsx to pdf
        command = ['unoconv', '-f', 'pdf']
        if user_password:
            command.extend(['--export=EncryptFile=true', '--export=DocumentOpenPassword=' + user_password])
        command.append('input.xlsx')
        subprocess.call(command)

        # read pdf file from disk
        with open('input.pdf', 'rb') as f:
            pdf = f.read()

        # remove xlsx and pdf files from disk
        if os.path.exists('input.xlsx'):
            os.remove('input.xlsx')
        if os.path.exists('input.pdf'):
            os.remove('input.pdf')

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline;filename=%s' % name
    app.logger.info(' ==> POST  /xlsx?filename=%s  ok' % name)
    return response

@app.route('/zip', methods=['POST'])
@authenticate
def zip():
    name = request.args.get('filename', 'unnamed.zip')
    app.logger.info('POST  /zip?filename=%s' % name)
    app.logger.info('Content-Type %s' % request.headers['Content-Type'])
    fileobj = io.BytesIO()

    if request.headers['Content-Type'] == 'application/json':
        data = json.loads(request.data.decode('utf-8'))

        htmls = json.loads(data['htmls'])
        css = CSS(string=base64.b64decode(data['css']), font_config=font_config)
        filenames = json.loads(data['filenames'])
        user_passwords = json.loads(data.get('user_passwords', '[]'))
        owner_passwords = json.loads(data.get('owner_passwords', '[]'))

        with zipfile.ZipFile(fileobj, mode="w") as archive:
            for index in range(len(filenames)):
                app.logger.info('Filename %s' % filenames[index])
                html = HTML(string=base64.b64decode(htmls[index]))
                html.write_pdf(filenames[index], stylesheets=[css], font_config=font_config)

                if user_passwords and index < len(user_passwords) and user_passwords[index]:
                    reader = PdfFileReader(filenames[index])
                    writer = PdfFileWriter()
                    writer.appendPagesFromReader(reader)

                    owner_password = owner_passwords[index] if owner_passwords and index < len(owner_passwords) else None
                    writer.encrypt(user_passwords[index], owner_pwd=owner_password)
                    with open(filenames[index], 'wb') as f:
                        writer.write(f)

                archive.write(filenames[index])

                if os.path.exists(filenames[index]):
                    os.remove(filenames[index])

    response = make_response(fileobj.getvalue())
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = 'inline;filename=%s' % name
    app.logger.info(' ==> POST  /zip?filename=%s  ok' % name)
    return response

@app.route('/multiple', methods=['POST'])
@authenticate
def multiple():
    name = request.args.get('filename', 'unnamed.pdf')
    app.logger.info('POST  /multiple?filename=%s' % name)
    data = json.loads(request.data.decode('utf-8'))
    htmls = data['htmls']
    user_password = data.get('user_password')
    owner_password = data.get('owner_password')
    documents = [HTML(string=html).render() for html in htmls]
    pdf = documents[0].copy([page for doc in documents for page in doc.pages]).write_pdf()

    if user_password:
        reader = PdfFileReader(io.BytesIO(pdf))
        writer = PdfFileWriter()
        writer.appendPagesFromReader(reader)
        writer.encrypt(user_password, owner_pwd=owner_password)

        with io.BytesIO() as f:
            writer.write(f)
            pdf = f.getvalue()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline;filename=%s' % name
    app.logger.info(' ==> POST  /multiple?filename=%s  ok' % name)
    return response


if __name__ == '__main__':
    app.run()
