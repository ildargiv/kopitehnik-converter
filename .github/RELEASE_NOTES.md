## v3.5.1

**Русский.** Новый режим `Converter.exe --edit <файл> [--ocr] [--out <результат.pdf>]`: открывает только редактор PDF (без главного окна) для PDF, Word, Excel, PowerPoint и сканов. Путь сохранённого PDF выводится последней строкой; код 0 — сохранено, 1 — закрыто без сохранения. Проверка обновлений в этом режиме отключена.

**English.** New mode `Converter.exe --edit <file> [--ocr] [--out <result.pdf>]`: opens only the PDF editor (no main window) for PDF, Word, Excel, PowerPoint and scans. The saved PDF path is printed as the last line; exit code 0 = saved, 1 = closed without saving. The update check is off in this mode.

**Deutsch.** Neuer Modus `Converter.exe --edit <Datei> [--ocr] [--out <Ergebnis.pdf>]`: öffnet nur den PDF-Editor (ohne Hauptfenster) für PDF, Word, Excel, PowerPoint und Scans. Der Pfad der gespeicherten PDF steht in der letzten Zeile; Code 0 = gespeichert, 1 = ohne Speichern geschlossen. Die Update-Prüfung ist in diesem Modus aus.

**Español.** Nuevo modo `Converter.exe --edit <archivo> [--ocr] [--out <resultado.pdf>]`: abre solo el editor de PDF (sin ventana principal) para PDF, Word, Excel, PowerPoint y escaneos. La ruta del PDF guardado se imprime en la última línea; código 0 = guardado, 1 = cerrado sin guardar. La búsqueda de actualizaciones está desactivada en este modo.

**Français.** Nouveau mode `Converter.exe --edit <fichier> [--ocr] [--out <résultat.pdf>]` : ouvre uniquement l'éditeur PDF (sans fenêtre principale) pour PDF, Word, Excel, PowerPoint et scans. Le chemin du PDF enregistré est affiché sur la dernière ligne ; code 0 = enregistré, 1 = fermé sans enregistrer. La recherche de mises à jour est désactivée dans ce mode.

**Português.** Novo modo `Converter.exe --edit <arquivo> [--ocr] [--out <resultado.pdf>]`: abre apenas o editor de PDF (sem janela principal) para PDF, Word, Excel, PowerPoint e digitalizações. O caminho do PDF salvo é impresso na última linha; código 0 = salvo, 1 = fechado sem salvar. A verificação de atualizações fica desativada nesse modo.

**Türkçe.** Yeni mod `Converter.exe --edit <dosya> [--ocr] [--out <sonuç.pdf>]`: PDF, Word, Excel, PowerPoint ve taramalar için yalnızca PDF düzenleyiciyi (ana pencere olmadan) açar. Kaydedilen PDF'nin yolu son satıra yazılır; çıkış kodu 0 = kaydedildi, 1 = kaydetmeden kapatıldı. Bu modda güncelleme denetimi kapalıdır.

**中文。** 新增模式 `Converter.exe --edit <文件> [--ocr] [--out <结果.pdf>]`:仅打开 PDF 编辑器(无主窗口),支持 PDF、Word、Excel、PowerPoint 和扫描件。保存后的 PDF 路径输出在最后一行;退出码 0 = 已保存,1 = 未保存关闭。此模式下不检查更新。

**日本語。** 新モード `Converter.exe --edit <ファイル> [--ocr] [--out <結果.pdf>]`:PDF、Word、Excel、PowerPoint、スキャンに対して PDF エディターだけを(メインウィンドウなしで)開きます。保存した PDF のパスは最終行に出力され、終了コード 0 = 保存、1 = 保存せず閉じた。このモードでは更新確認は行いません。


v3.5.1 replaces the unpublished v3.5 build: the PDF library is pinned (`pymupdf<2`) so the installer starts correctly. / v3.5.1 заменяет неопубликованную сборку v3.5: библиотека PDF закреплена (`pymupdf<2`), установщик запускается.

---
SHA-256 of `KopiTehnik-Converter-Setup.exe` is in `SHA256SUMS.txt` (check: `certutil -hashfile KopiTehnik-Converter-Setup.exe SHA256`). Built by GitHub Actions from this repository's source; build attestation is attached.
