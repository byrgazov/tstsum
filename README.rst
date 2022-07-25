
Задание
-------

Написать сервис на Python, который имеет 3 REST ендпоинта:

1. Получает по HTTP имя CSV-файла (пример файла во вложении) в хранилище и
   суммирует каждый 10й столбец.
2. Показывает количество задач на вычисление, которые на текущий момент в работе.
3. Принимает ID задачи из п.1 и отображает результат в JSON-формате.

Требования:

* Сервис должен поддерживать обработку нескольких задач от одного клиента одновременно.
* Сервис должен иметь возможность горизонтально масштабироваться и загружать
  данные из AWS S3 и/или с локального диска.
* Количество строк в csv может достигать 3*10^6.
* Подключение к хранилищу может работать нестабильно.


Сборка и запуск из исходников
-----------------------------

Предварительные требования:

* RabbitMQ
* Minio (S3)

Настройка переменных окружения (единственный способ конфигурации):

.. code:: bash

  $ export ZODB_STORAGE = "zeo://localhost:8100/?connection_pool_size=10&cache_size=100mb"
  $ export MINIO_ENDPOINT = "localhost:9000"
  $ export MINIO_ACCESS_KEY = "minioadmin"
  $ export MINIO_SECRET_KEY = "minioadmin"
  $ export CONEY_BROKER_URI = "amqp://user:password@localhost/"

Установка:

.. code:: bash

  $ virtualenv --python=python3 .venv
  $ .venv/bin/pip install -U pip zc.buildout
  $ .venv/bin/buildout

Инициализация схемы и запуск:

.. code:: bash

  # терминал 1
  $ bin/tstsum init
  $ bin/zeosrv start

  $ bin/flask run --reload
  # или
  $ bin/waitress-serve --port=5000 --call tstsum.app:make_wsgi

  # терминал 2 (не забыть про переменные окружения)
  $ bin/tstsum service-sum

  # терминал 3
  $ bin/tstsum service-sum

  # ...

Генерирование данных:

.. code:: bash

  $ bin/tstsum generate-csv --columns=100 --rows=100
  $ bin/tstsum generate-csv --columns=100 --rows=1000
  $ bin/tstsum generate-csv --columns=1000 --rows=10000
  # ...

Обращение к API:

.. code:: bash

  $ bin/http http://localhost:5000/api/list_files
  $ bin/http http://localhost:5000/api/schedule_work filepath=<filepath1>
  $ bin/http http://localhost:5000/api/schedule_work filepath=<filepath2>
  $ bin/http http://localhost:5000/api/list_works
  $ bin/http http://localhost:5000/api/get_result/<workid1>
  $ bin/http http://localhost:5000/api/get_result/<workid2>
