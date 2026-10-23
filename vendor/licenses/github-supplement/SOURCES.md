# Supplemental notices for the GitHub release

This supplement accompanies Xiaomi Remote Assistant 0.1.1. It does not modify the
verified installer or its corresponding source snapshot. License files are
copied verbatim; copyright notices and license terms have not been rewritten.

## Local distribution notices

| File | Distribution and origin | Scope |
| --- | --- | --- |
| `Python-3.11.14-LICENSE.txt` | CPython 3.11.14 Windows x86-64 runtime distribution, root `LICENSE.txt`, as installed by uv | Complete license file shipped with that Python runtime, including its included component notices. |
| `PortAudio-binaries-README.md` | `sounddevice` 0.5.6 wheel, `_sounddevice_data/portaudio-binaries/README.md` | Original binary bundle attribution and packaging notes, including descriptions of other upstream binaries not necessarily used by this application. |
| `PortAudio-binaries-build-libs.yml` | `sounddevice` 0.5.6 wheel, `_sounddevice_data/portaudio-binaries/.github/workflows/build-libs.yml` | Original build recipe supplied with that binary bundle. Both Windows and macOS jobs check out `PortAudio/portaudio` at `v19.7.0`; this is the direct basis for selecting the corresponding upstream license. |

Python upstream source: <https://github.com/python/cpython/tree/v3.11.14>.
The Python notice above was copied from the actual local runtime distribution,
not reconstructed from the website.

## Versioned official upstream notices

The files below were obtained read-only through the GitHub API from official
upstream repositories on 2026-10-23. Each decoded payload was checked against the
Git blob SHA-1 returned by the API before saving. SHA-256 values are also recorded.

- **PyWinRT 3.2.1:** the installed runtime and Windows projection packages are
  version 3.2.1 and declare MIT in their package metadata. The full notice is from
  the matching official `v3.2.1` source tag.
- **PortAudio 19.7.0:** the installed sounddevice 0.5.6 wheel's bundled workflow
  pins `v19.7.0`, as recorded above. The full notice is from that official tag.
- **QtBase 6.8.3:** the application uses PySide6/Qt 6.8.3. This directory contains
  the original files in `qt/qtbase`'s `LICENSES/` at official tag `v6.8.3`, without
  selecting or rewriting terms. Inclusion of a license text does not assert that
  every license in this source collection applies to every application binary.

| Local file | Official source | Git blob SHA-1 | SHA-256 |
| --- | --- | --- | --- |
| `PortAudio-19.7.0-LICENSE.txt` | [https://github.com/PortAudio/portaudio/blob/v19.7.0/LICENSE.txt](https://github.com/PortAudio/portaudio/blob/v19.7.0/LICENSE.txt) | `e0ac4e8a0c0188cece03c15e956b800f34e1c449` | `ec52a1952d701f94e5135719a47376da4ee0b4a0201f1cafb49f61db6480ac3d` |
| `PyWinRT-3.2.1-LICENSE.txt` | [https://github.com/pywinrt/pywinrt/blob/v3.2.1/LICENSE](https://github.com/pywinrt/pywinrt/blob/v3.2.1/LICENSE) | `09f9a09b1ed6862b422f8ec9eee0f9f5dead0f2e` | `6e898069e8b3c6d8d23dc70ac7067cc2b7c9db14c36df873026758db82c0891d` |
| `QtBase-6.8.3-LICENSES/AFL-2.1.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/AFL-2.1.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/AFL-2.1.txt) | `011d6d489bca75a655649e477efb3cb06e1c8007` | `93bb4f7417aa775bab9026cc3d0af28aeb64451fc5a8ec651876785edd8eaf9b` |
| `QtBase-6.8.3-LICENSES/Apache-2.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Apache-2.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Apache-2.0.txt) | `136d90045663ab0acaeff2a3ecf0013c968de8c9` | `e3ba223bb1423f0aad8c3dfce0fe3148db48926d41e6fbc3afbbf5ff9e1c89cb` |
| `QtBase-6.8.3-LICENSES/BSD-2-Clause.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-2-Clause.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-2-Clause.txt) | `7e7fb71e0fce53ef1661277c5b4503c6e049a615` | `8fda146749ca071ac9cdce2e24d25444676ea48d1f9dccc2b7c15c054b717db8` |
| `QtBase-6.8.3-LICENSES/BSD-3-Clause.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-3-Clause.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-3-Clause.txt) | `b91bbd89468099ae5c3028f176783976ca538187` | `9f0490f18656c6f2435bd14f603ef0c96434d1825615363dce43abb42ed1dcce` |
| `QtBase-6.8.3-LICENSES/BSD-4-Clause.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-4-Clause.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSD-4-Clause.txt) | `965aab0ef12f482d55d215fbf8d10595cf2a9618` | `83faa0d205c316ce3efeafee465b6a165914fb29595968c08dc6437021b7b6fd` |
| `QtBase-6.8.3-LICENSES/BSL-1.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSL-1.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/BSL-1.0.txt) | `9cc4741747a0f8d7e107a74cae898a69ad25fd21` | `3abd6471b9a9a08d65ce771143f8e278bb4c1aeb10c1c2d476935a6b049653f5` |
| `QtBase-6.8.3-LICENSES/Bitstream-Vera.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Bitstream-Vera.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Bitstream-Vera.txt) | `df52c1709bea171104d41bf084313ea434858423` | `7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93` |
| `QtBase-6.8.3-LICENSES/CC0-1.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/CC0-1.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/CC0-1.0.txt) | `0e259d42c996742e9e3cba14c677129b2c1b6311` | `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` |
| `QtBase-6.8.3-LICENSES/FTL.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/FTL.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/FTL.txt) | `c406d150fa57aaf7a5b950b6cf302daeba1d0bb9` | `08c135755dd589039470f1fdbb400daaabaaa50d0b366d19cebff4d22986baa1` |
| `QtBase-6.8.3-LICENSES/GFDL-1.3-no-invariants-only.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GFDL-1.3-no-invariants-only.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GFDL-1.3-no-invariants-only.txt) | `857214dd84593e0bacaac0211d76de0b69f2fa18` | `110535522396708cea37c72a802c5e7e81391139f5f7985631c93ef242b206a4` |
| `QtBase-6.8.3-LICENSES/GPL-2.0-only.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-2.0-only.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-2.0-only.txt) | `d159169d1050894d3ea3b98e1c965c4058208fe1` | `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643` |
| `QtBase-6.8.3-LICENSES/GPL-2.0-or-later.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-2.0-or-later.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-2.0-or-later.txt) | `d159169d1050894d3ea3b98e1c965c4058208fe1` | `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643` |
| `QtBase-6.8.3-LICENSES/GPL-3.0-only.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-3.0-only.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-3.0-only.txt) | `94a9ed024d3859793618152ea559a168bbcbb5e2` | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |
| `QtBase-6.8.3-LICENSES/HPND.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/HPND.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/HPND.txt) | `e54a695e16e145af42c1d514edc2652596427115` | `67ac968431270291f5e9cd3ed76705e1169f57082ee102093b2543b28cef63cf` |
| `QtBase-6.8.3-LICENSES/IJG.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/IJG.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/IJG.txt) | `eec5341d1c4e9ded532479684d061ffe3f6915b2` | `1cb448f5e2e6d3aca60943f4eee1a04675628dc0266a074a42bc1560ebc28d61` |
| `QtBase-6.8.3-LICENSES/IPL-1.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/IPL-1.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/IPL-1.0.txt) | `b779b1402a4a7c33310aa3c908f53bff5c004be4` | `d5328e672fb1bff47ee18e890784541453380081cf3771bb7b3c06fc19c7d503` |
| `QtBase-6.8.3-LICENSES/Imlib2.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Imlib2.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Imlib2.txt) | `b8430d80a3fcf6f8facb955e2fb0b1b769615794` | `8846f2baba1a7f4c36f7ca19a923a000d8a21afa37cf0fe006f6ce88a6058a89` |
| `QtBase-6.8.3-LICENSES/LGPL-3.0-only.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LGPL-3.0-only.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LGPL-3.0-only.txt) | `65c5ca88a67c30becee01c5a8816d964b03862f9` | `da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768` |
| `QtBase-6.8.3-LICENSES/Libpng.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Libpng.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Libpng.txt) | `81c1c4dd534fdd23ea97bdcfc7dcdc9cd46f3576` | `58fe669792f9b4e0740bf75ecfe90b5326128bb2ce7e27e1c342abd9db4d8ea6` |
| `QtBase-6.8.3-LICENSES/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt) | `9f4ae05fa5c02955713964a0f88a6bb67ad03be5` | `0526625fcc746a42d3f19a0ab357d3dc8479fdbe3bfd168825498f50215c7a63` |
| `QtBase-6.8.3-LICENSES/LicenseRef-ICC-License.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-ICC-License.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-ICC-License.txt) | `e25b1d39f1ee489362fe15dae6b01b9522735dc7` | `9e34ff47b3a44814e183342e7e198d127a6740e29d20e8381fba7688dafc79dd` |
| `QtBase-6.8.3-LICENSES/LicenseRef-Lcs-Telegraphics.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-Lcs-Telegraphics.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-Lcs-Telegraphics.txt) | `6c03ad2aff71b8e39a282376bbd20179f5befbc5` | `c10225ebbd5191bfdd761b0d7752c785f2453ab665d6c454473fb12d254668aa` |
| `QtBase-6.8.3-LICENSES/LicenseRef-Qt-Commercial.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-Qt-Commercial.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-Qt-Commercial.txt) | `825b1f358b1f42d762112defbf0a193c9d968488` | `9b1f50aae6267f9d5e0ceb6775ee86450262c25ec7c0573e151fe5d3f18a4700` |
| `QtBase-6.8.3-LICENSES/LicenseRef-SHA1-Public-Domain.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-SHA1-Public-Domain.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LicenseRef-SHA1-Public-Domain.txt) | `2ebbf9a78ad592c705e5b6e22e20cfb8f1d11abf` | `65d86b8ec6b1cd8b8f6e64fd8710274ba00d6a3c520e00dfdcd1c3d2071f3305` |
| `QtBase-6.8.3-LICENSES/Linux-syscall-note.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Linux-syscall-note.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Linux-syscall-note.txt) | `82054e66953e0ebf83c4a61bfc1deaaddf755c80` | `3f9e477523febab58de8b716ccfbcf02e6ef1c8e7728953905e8558637abe2a9` |
| `QtBase-6.8.3-LICENSES/MIT-Khronos-old.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT-Khronos-old.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT-Khronos-old.txt) | `06d18a567301e6e35d4a7c5fa7b443cb1ac66ea9` | `3c58021633974f9ed3c3d445a374240a5244fd039628f4d7f6f3e674bc8e6694` |
| `QtBase-6.8.3-LICENSES/MIT-open-group.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT-open-group.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT-open-group.txt) | `8b6789ae03ca8e0791f422c4ba656faf2b1f0221` | `c55d2ab72d8a4f9e9cd8fbd1379268e575e8cfa16874affa5899b75a6d754514` |
| `QtBase-6.8.3-LICENSES/MIT.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MIT.txt) | `bc65af3cbd380a2b5e6b3f37d359d3c51ff0fa71` | `d040359701c01996a017d5c515678929cd1b0625e64cb86db44025fbb6cdf1fc` |
| `QtBase-6.8.3-LICENSES/MPL-2.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MPL-2.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/MPL-2.0.txt) | `d0a1fa1482eea82e19510e7920cbe3a03e41f691` | `3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04` |
| `QtBase-6.8.3-LICENSES/Qt-GPL-exception-1.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Qt-GPL-exception-1.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Qt-GPL-exception-1.0.txt) | `d0322bf0e4e1d484d35cc6a1d96fa2b65b9d579b` | `40678d338ce53cd93f8b22b281a2ecbcaa3ee65ce60b25ffb0c462b0530846b2` |
| `QtBase-6.8.3-LICENSES/SPL-1.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/SPL-1.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/SPL-1.0.txt) | `55c5da3447a1e689bafe435dda2768f968f41f2e` | `f58f2f30909982445f97f1a61667261920a7caeab21ef5bea1b740f5b144d141` |
| `QtBase-6.8.3-LICENSES/Unicode-3.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Unicode-3.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Unicode-3.0.txt) | `739715c45cf49d00f3b3832cb353f8ffd385eb22` | `80bb6294022d8764adb36a9d65ebb6bd94efb1865918a71e31e6c247607d7634` |
| `QtBase-6.8.3-LICENSES/X11.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/X11.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/X11.txt) | `e1cd1e01e60d42aa148a95f0fe318cc1a17480f6` | `e2936c6509784b4f0ec27bac74182393866fad9422b29a70e085ff14aba87193` |
| `QtBase-6.8.3-LICENSES/Xerox.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Xerox.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Xerox.txt) | `481d3b1493661f7f04e6792c6099c2bada95279b` | `b6bc52205d01e10cf43dbb7b8aec06dcaa3b21d1486e7c9c0bec329ee8244d8d` |
| `QtBase-6.8.3-LICENSES/Zlib.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Zlib.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/Zlib.txt) | `9c57e18006ec54be5d52d0bd4ff04cd5432c975f` | `d7e3139972874dc8abdbbfce27ec1e6f942b28279dd7d27453630a8b4610e080` |
| `QtBase-6.8.3-LICENSES/blessing.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/blessing.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/blessing.txt) | `7a1b711a6b86f81b9b3943340f9f47c5a612f2f0` | `592db1199aab67aafe4515db9808b420db122083807c5329b2f061951e79acbe` |
| `QtBase-6.8.3-LICENSES/libpng-2.0.txt` | [https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/libpng-2.0.txt](https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/libpng-2.0.txt) | `25f298f0fcfd8757bbd9a6386d8fcb2d644cfce9` | `7317e078e2d3b5d7ba5a6159e650945153262b44b76f6700f8e9edb261c5143e` |

## Scope and remaining limits

The QtBase collection is not a claim to include every component-specific
copyright notice, every Qt plugin's third-party materials, or QtWebEngine's full
Chromium third-party inventory. The existing `../LGPL-3.0.txt` and notices under
`../python-packages/` remain part of the project. This supplement records exact
available notices and provenance; it is not a legal certification or a claim that
all bundled components share one license.
