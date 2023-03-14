Описание вспомогательных инструментов
-------------------------------------

Инструментарий корректно работает с Ubuntu 18.
Необходимые зависимости устанавливаются командой:

```shell
sudo apt install git openjdk-11-jdk python3 python3-dev ant lcov cmake libmpc-dev lib32z1 libxslt-dev libpq-dev
```

Модули python:

```shell
sudo pip3 install requests ujson graphviz ply pytest atomicwrites pathlib2 more-itertools pluggy py attrs setuptools six django==2.1 clade psycopg2
```

1. Инструмент klever — web-интерфейс, отвечающий за визуализацию результатов.
Репозиторий: https://github.com/mutilin/klever.git
Развёртывание web-интерфейса описано в инструкции docs/web_interface.txt.

2. Инструмент CIL отвечает за объединение исходных файлов и их упрощение.
Репозиторий https://forge.ispras.ru/git/cil.git
Примечание: инструмент может быть собран только при наличии ocaml-4.01 или более ранних версий (например, на Ubuntu 14.04 или более ранних версиях) согласно инструкции README.md.
Для более поздних версий ocaml в репозитории имеется 2 собранные версии:
 - tools/cil.xz (версия 1.5.1) - используется по умолчанию;
 - tools/astraver-cil.xz (на основе Frama-C 18.0).
Для использования второй версии необходимо выполнить:
```
make install-astraver-cil DEPLOY_DIR=<директория, в которую будет развернут инструментарий CV>
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
Репозиторий: https://forge.ispras.ru/git/cif.git

6. Верификационное облако (Verification Cloud) позволяет распараллелить решение верификационных задач на нескольких машинах.
Репозиторий: git@gitlab.com:mutilin/vcloud.git
