Описание вспомогательных инструментов
-------------------------------------

Инструментарий корректно работает с Ubuntu 18.
Необходимые зависимости устанавливаются командой:

```shell
sudo apt install git openjdk-11-jdk python3 python3-dev ant lcov cmake libmpc-dev lib32z1 libxslt-dev libpq-dev
```

Модули python:

```shell
sudo pip3 install requests ujson graphviz ply pytest atomicwrites pathlib2 more-itertools pluggy py attrs setuptools six django==2.1 clade psycopg2 pyyaml pycparser sympy
```

1. Инструмент CVV — web-интерфейс, отвечающий за визуализацию результатов.
Репозиторий: https://github.com/vmordan/cvv
Развёртывание web-интерфейса описано в инструкции docs/web_interface.txt.

2. Инструмент CIL отвечает за объединение исходных файлов и их упрощение.
По умолчанию используется старая версия (имеются только исходники, поддержка кода не ведется).
Репозиторий с новой поддерживаемой версией:
https://forge.ispras.ru/projects/astraver/repository/framac?utf8=%E2%9C%93&rev=20.0.
Для сборки инструмента необходимо обратиться к инструкции `INSTALL.md`.
Можно использовать уже собранную версию:
```shell
make install-frama-c-cil DEPLOY_DIR=<директория, в которую будет развернут инструментарий CV>
```

3. Инструмент BenchExec отвечает за ограничение и измерение вычислительных ресурсов.
Репозиторий: https://github.com/sosy-lab/benchexec.git.
НЕ работает с Ubuntu 22.

4. Инструмент CPAchecker отвечает непосредственно за верификацию.
Требуемые версии инструмента хранятся в файле cpa.config в корневой директории в формате
`<mode>;<репозиторий>;<ветка>;<ревизия>`.
Для скачивания всех указанных версий CPAchecker необходимо выполнить:
```shell
make download-cpa
```
Для удаления уже установленных версий CPAchecker необходимо выполнить:
```shell
make clean-cpa
```

5. Инструмент CIF требуется для проверки коммитов.
По умолчанию данный инструмент не устанавливается.
Репозиторий: `https://github.com/ldv-klever/cif`.
Для установки необходимо использовать уже собранную под `linux-x86_64` версию:
```shell
DEPLOY_DIR=<директория, в которую будет развернут инструментарий CV> make install-cif-compiled
```
либо собрать из исходников (предварительно необходимо установить пакет `flex`):
```shell
DEPLOY_DIR=<директория, в которую будет развернут инструментарий CV> make install-cif
```
Сборка занимает порядка 30 минут.

6. Верификационное облако (Verification Cloud) позволяет распараллелить решение верификационных задач на нескольких машинах.
Репозиторий: git@gitlab.com:mutilin/vcloud.git
