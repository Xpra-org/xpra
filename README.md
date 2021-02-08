# Xpra 3.1.x branch
This branch of xpra will be replacing the 3.0.x LTS branch, for more details see [versions](https://github.com/Xpra-org/xpra/wiki/Versions)

Unlike the _fixes-only_ policy normally applied to the v3.0.x branch,
the 3.1.x branch will include backports from newer versions that are not strictly bug fixes.
Either changes that are low risk (ie: independant new features) or changes that have been thoroughly tested in new versions.

---

## Pending testing:
* https://github.com/Xpra-org/xpra/commit/61cc14f808cd5a37816a84d5d4e8b6d710e47091
* scaling and cursors: r24125, r24128, r24131
* faster startup: #2411, #2414
* wheel direction fixes from #1797
* #2902 - stderr part

## Smaller changes:
* #2518, #2519, #2520, #2538
* UDP fixes: r25009, r25006, ..
* #2566 + r25093
* r24348
* #2567
* r25212 + r25301 + r25314
* #2601
* #2603
* #2625
* r25689
* #2649 (memleak without the changes?)
* backport all clipboard fixes, ie: #2674
* #2705: just bring the whole updated js code?
* #2721
* #2719
* #2749
* #451
* r27034 : expose machine-id
* #2881
* r27604
* #2904
* #2914
* #2921
* r27856
* r27905
* r28037, r28038, r28039
* r28048 + r28049
* r28050
* r28174 + r28175 + r28177 + r28178
* r28210 + r28211 + r28212
* r28193 + r28194
* r28250

## Bigger changes that may not make the cut:
* r27656
* r27755
* #2907
* #2927
