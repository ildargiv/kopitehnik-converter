# Конвертор для ИИ-агентов (MCP)

Программа умеет работать как MCP-сервер: ИИ-агент (Claude, Hermes и любой другой клиент MCP) получает все функции как инструменты с текстовыми параметрами. Экран и зрение не нужны: результат проверяется числами (размеры, яркость, контраст) и текстом PDF, а при желании ещё и картинкой.

Транспорт стандартный: stdio. Агент сам запускает программу командой `Converter.exe --mcp`, окно не открывается. Сервер работает только на этом компьютере и ничего не слушает по сети.

## Подключение

Установленная программа лежит в `%LOCALAPPDATA%\Programs\KopiTehnik Converter\Converter.exe`. Готовую настройку с точным путём покажет кнопка «Подключить ИИ-агента» в окне «О программе».

### Hermes Agent
Файл `~/.hermes/config.yaml` (в Windows `C:\Users\<имя>\.hermes\config.yaml`):

```yaml
mcp_servers:
  converter:
    command: "C:\Users\<имя>\AppData\Local\Programs\KopiTehnik Converter\Converter.exe"
    args: ["--mcp"]
    timeout: 600
    connect_timeout: 120
```

Потом в сессии Hermes выполните `/reload-mcp` (или перезапустите его). Проверка: `hermes mcp test converter`. Увеличенные таймауты нужны, потому что exe при запуске распаковывается (несколько секунд), а большие партии файлов конвертируются долго.

### Claude Desktop, Cursor, Cline и другие
Раздел `mcpServers` в настройках клиента:

```json
{
  "mcpServers": {
    "kopitehnik-converter": {
      "command": "C:\Users\<имя>\AppData\Local\Programs\KopiTehnik Converter\Converter.exe",
      "args": ["--mcp"]
    }
  }
}
```

### Claude Code
```
claude mcp add converter -- "C:\Users\<имя>\AppData\Local\Programs\KopiTehnik Converter\Converter.exe" --mcp
```

### Из исходников
`command`: `python`, `args`: `["<папка>\app.py", "--mcp"]` (нужны PySide6, pillow, pillow-heif, openpyxl, pymupdf).

## Инструменты

| Инструмент | Что делает |
|---|---|
| `app_info` | форматы, раскладки листов, бумага, найденные Office/LibreOffice и принтеры (вызывать первым) |
| `list_files` | поддерживаемые файлы в папке |
| `inspect_file` | размеры, dpi, страницы, яркость и контраст в числах |
| `convert` | JPEG/PNG/TIFF/PDF, кадр (3:2, 4:3, 7:5, 1:1, A4, свой размер в см/мм/дюймах), поворот, зеркало, цвет, архивы |
| `make_sheet` | несколько фото на листе: 10×15 и 9×12 на A4, документы 3×4, 3,5×4,5, 4×6, контрольный лист, своя сетка или размер |
| `preview` | готовая страница или лист картинкой плюс числа |
| `pdf_info`, `pdf_get_text`, `pdf_find_text` | страницы PDF, текст по строкам с координатами, шрифтом и цветом, поиск |
| `pdf_edit` | заменить текст с тем же видом, вписать надпись, стереть область, вставить картинку; результат в новый файл |
| `pdf_pages` | склеить, оставить или переставить, удалить, повернуть страницы, разрезать |
| `list_printers`, `print_files` | печать: принтер, бумага, ориентация, копии, листы, цвет или ч/б, масштаб; `printer: "pdf"` пишет в файл, `dry_run` только считает листы |

Цвет задаётся числами от −100 до 100: `brightness`, `contrast`, `saturation`, `gamma` (средние тона), `red`, `green`, `blue`, `cyan`, `magenta`, `yellow`, плюс `auto` 0..100 (автокоррекция) и `wb` (баланс белого). Координаты в PDF это пункты (1/72 дюйма) от левого верхнего угла страницы.

Исходные файлы не меняются. `print_files` без `dry_run` и без `printer: "pdf"` печатает на бумаге по-настоящему, поэтому клиент обычно спрашивает подтверждение.

## Пример для агента

1. `app_info`
2. `make_sheet` с `{"folder": "D:\фото", "out_dir": "D:\лист", "preset": "p10x15_a4", "format": "PDF"}`
3. `preview` с теми же файлами и `{"sheet": {"preset": "p10x15_a4"}}`: проверить число фото на листе и яркость
4. `print_files` с `{"files": ["D:\лист\sheets.pdf"], "printer": "EPSON L8050 Series", "paper": "a4", "dry_run": true}`, затем без `dry_run`

## Лицензия
Редактор PDF использует PyMuPDF (AGPL-3.0), поэтому программа открыта под AGPL-3.0, как и сервер.
