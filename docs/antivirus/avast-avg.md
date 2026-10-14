# Заявка о ложном срабатывании: Avast / AVG

Куда: https://www.avast.com/false-positive-file-form.php

Отправляет владелец после выхода релиза и проверки на VirusTotal. Заменить X.Y и места в угловых скобках.

```
Subject: False positive: KopiTehnik Converter X.Y (Avast / AVG)

Hello,

Please review and whitelist the following file, it is a false positive.

- Product: KopiTehnik Converter, free open-source (AGPL-3.0) Windows software for photo labs
- Source code: https://github.com/ildargiv/kopitehnik-converter
- File: KopiTehnik-Converter-Setup.exe (Converter.exe inside)
- SHA-256: <ВСТАВИТЬ из SHA256SUMS.txt>
- Download: https://github.com/ildargiv/kopitehnik-converter/releases/tag/vX.Y
- VirusTotal: <ВСТАВИТЬ ссылку на отчёт>
- Detection name: <ВСТАВИТЬ название срабатывания>

The program is built by GitHub Actions from the public source (workflow .github/workflows/release.yml, build attestation attached to the release). It is packaged with PyInstaller (Python and Qt), a known cause of heuristic detections. It uses the network only to ask GitHub for the latest release and to download the installer on the user's request, and it changes no system settings (per-user install, no administrator rights).

Contact: Ildar Gaisin, ildargiv@gmail.com
```
