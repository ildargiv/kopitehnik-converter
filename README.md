# КопиТехник Конвертор

**Бесплатная программа для Windows для профессиональной печати в фотоцентрах: пакетная конвертация, цвет, листы для печати, редактор PDF и печать с предпросмотром. Управляется и человеком, и ИИ-агентом.**

*English: free Windows software for photo labs and print shops. Batch-convert photos and documents to JPG/PNG/TIFF/PDF, colour-correct, lay out multi-photo print sheets (10x15, ID photos, contact sheets), edit PDF and print with preview. It is also an MCP server, so AI agents (Claude, Hermes, Cursor and others) can run the whole workflow through tools. Licence: AGPL-3.0.*

![Цветокоррекция в реальном времени](docs/images/demo.gif)

| Главное окно | Лист 10×15 с метками реза |
|---|---|
| ![Главное окно](docs/images/main.png) | ![Лист для печати](docs/images/sheet.png) |
| ![Цвет](docs/images/color.png) | ![Светлая тема](docs/images/light.png) |

*Скриншоты сделаны на сгенерированных тестовых изображениях.*

## Зачем он фотоцентру
Типовой день приёмщика: клиент приносит флешку с HEIC с телефона, PSD, сканы, Word и PDF. Всё нужно привести к одному виду, подправить цвет, разложить на листы 10×15 или фото на документы, поставить метки реза и отправить на принтер. Конвертор делает это одной программой и одним проходом по папке.
- **Приём любых файлов:** JPG, PNG, WebP, BMP, GIF, TIFF, HEIC, PSD, PDF, SVG, TXT, HTML, XLSX, архивы ZIP (RAR и 7z при установленных 7-Zip или WinRAR), документы Word, PowerPoint и Excel через Microsoft Office или LibreOffice.
- **Цвет:** автокоррекция, пипетка баланса белого, яркость, контраст, насыщенность, средние тона, отдельно красный, зелёный, синий, голубой, пурпурный и жёлтый. Встроенный ICC-профиль фото учитывается и переводится в sRGB.
- **Печатный лист:** готовые раскладки (фото 10×15 и 9×12 на A4, 3×4, 3,5×4,5 и 4×6 на документы, контрольный лист), своя сетка или размер, поля, зазор, копии, поворот под ячейку, метки реза, подписи.
- **Кадр:** обрезка 3:2, 4:3, 5:4, 7:5, 1:1, 16:9, A4 и свой размер в см, мм или дюймах, поворот, зеркало.
- **Печать:** предпросмотр листа на бумаге, выбор принтера и его свойств, бумага A3, A4, A5, A6, 10×15, 13×18, 15×21, 20×30, Letter, поля, копии, диапазон листов, цвет или ч/б, размер «вписать», «заполнить без полей» или реальный по dpi.
- **Редактор PDF:** вписать текст, взять строку или абзац и исправить или передвинуть, стереть область. Исходный файл не меняется.
- **Пакетная обработка** в несколько потоков и командная строка: `Converter.exe --convert <папка> <результат>`.

## Управление ИИ-агентами (MCP)
Программа работает как **MCP-сервер**: ИИ-агент получает все функции как инструменты с текстовыми параметрами. Окно и зрение не нужны: результат проверяется числами (размеры, яркость, контраст), текстом PDF и при желании картинкой-превью. Так агенту можно поручить рутину фотоцентра, например: «разложи фото из папки на листы 10×15, проверь яркость, посчитай листы и отправь на принтер после моего подтверждения».

- Транспорт stdio. Сервер работает только на вашем компьютере и ничего не слушает по сети.
- Подходит для Claude Desktop, Claude Code, Hermes Agent, Cursor, Cline и любого клиента MCP.
- Инструменты: `app_info`, `list_files`, `inspect_file`, `convert`, `make_sheet`, `preview`, `pdf_info`, `pdf_get_text`, `pdf_find_text`, `pdf_edit`, `pdf_pages`, `list_printers`, `print_files`.
- Печать безопасна: у `print_files` есть `dry_run` (только считает листы) и `printer: "pdf"` (пишет в файл). Исходные файлы не меняются.

Подключение: `Converter.exe --mcp`. Готовая настройка есть в «О программе» → «Подключить ИИ-агента». Подробно, с примерами для каждого клиента: [MCP.md](MCP.md).

## Установка
**[Скачать установщик KopiTehnik-Converter-Setup.exe](https://github.com/ildargiv/kopitehnik-converter/releases/latest)** (раздел Releases): без прав администратора, с ярлыками, удаление через «Приложения». Новые версии выходят в группе https://vk.ru/icc_profil. Интерфейс на 8 языках (русский, английский, испанский, немецкий, французский, португальский, турецкий, китайский; язык Windows определяется сам), тёмная и светлая темы.

## Запуск из исходников
Нужен Python 3.10 или новее.

    pip install PySide6 pillow pillow-heif openpyxl pymupdf
    python app.py

## Сборка exe
    pip install pyinstaller
    pyinstaller converter.spec        # результат в dist\Converter.exe

Полная версия со своим LibreOffice (работает на компьютерах без офиса; папка около 850 МБ, zip около 380 МБ):

    python tools/make_full.py [папка LibreOffice]   # результат в dist\Converter-full и dist\Converter-full.zip

Без аргумента берётся LibreOffice, установленный на этом компьютере. Подойдёт и переносная версия (LibreOffice Portable): укажите её папку `App\libreoffice`.

## Устройство
- `core/loaders.py` — чтение файлов любого формата в страницы
- `core/office.py` — поиск Microsoft Office и LibreOffice, документы в PDF
- `core/imaging.py` — цвет, поворот, обрезка, сохранение
- `core/sheet.py` — несколько фото на одном листе
- `core/batch.py` — поиск файлов, архивы, пакетная обработка в нескольких потоках, вывод в PDF
- `ui/main_window.py` — главное окно; `ui/programs.py` — окно «Программы»; `ui/printing.py` — печать; `ui/pdf_editor.py` — редактор PDF
- `ui/widgets.py`, `ui/theme.py`, `ui/i18n.py` — виджеты, тема, тексты интерфейса
- `core/mcp_server.py`, `core/mcp_tools.py`, `core/pdftools.py`, `core/printjob.py` — MCP-сервер, его инструменты, правка PDF и печать без окна
- `tools/make_full.py` — полная сборка с LibreOffice

## Лицензия
Copyright (C) Гайсин Ильдар Вильсурович. Программа свободная, распространяется на условиях GNU Affero General Public License v3 (файл `LICENSE`): её можно бесплатно использовать, изучать, изменять и распространять, исходный код должен оставаться открытым. Лицензии сторонних библиотек: `THIRD_PARTY_NOTICES.txt`.

## Автор
**Гайсин Ильдар Вильсурович**, разработчик программы, КопиТехник: фотоцентр и профессиональная печать.
Новости, новые версии и связь: группа ВКонтакте https://vk.ru/icc_profil

*Author: Ildar Gaisin (Gaisin Ildar Vilsurovich), developer of KopiTehnik Converter, a photo lab and professional printing company. News and releases: https://vk.ru/icc_profil*
