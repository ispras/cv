Описание вспомогательных инструментов
-------------------------------------

Для корректной работы вспомогательных инструментов необходимо наличие следующих зависимостей:
 - git;
 - svn, версия не ниже 1.9;
 - java, версия не ниже 1.8;
 - python, версия не ниже 3.4;
 - python-dev (Ubuntu), python-devel (Fedora);
 - модули python:
   - requests;
   - ujson;
   - graphviz;
   - ply;
   - pytest;
   - atomicwrites;
   - pathlib2;
   - more-itertools;
   - pluggy;
   - py;
   - attrs;
   - setuptools;
   - six;
   - django;
   - psycopg2;
   - clade.
 - ant;
 - lcov;
 - cmake;
 - libmpc-dev (Ubuntu), libmpc-devel (Fedora);
 - lib32z1;
 - libxslt-devel;
 - libxml2-devel.x86_64;
 - clade (cм. п. 2).

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
НЕ работает с Ubunut 22.

4. Инструмент CPAchecker отвечает непосредственно за верификацию.
Требуемые версии инструмента хранятся в файле cpa.config в корневой директории в формате
`<mode>;<репозиторий>;<ветка>;<ревизия>`.
Для скачивания всех указанных версий CPAchecker необходимо выполнить:
```
make download-cpa
```

5. Инструмент CIF требуется для проверки коммитов.
Репозиторий: https://forge.ispras.ru/git/cif.git

6. Верификационное облако (Verification Cloud) позволяет распараллелить решение верификационных задач на нескольких машинах.
Репозиторий: git@gitlab.com:mutilin/vcloud.git
