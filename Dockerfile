FROM python:3.7.2-stretch

WORKDIR /usr/src/app

COPY requirements.txt ./
COPY dist/bitshares-1.2.1-py3.7.egg ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip uninstall -y bitshares
RUN python -m easy_install bitshares-1.2.1-py3.7.egg
COPY . .

CMD [ "/bin/bash" ]
