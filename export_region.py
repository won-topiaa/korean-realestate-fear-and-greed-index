"""수도권·광역시 지도 페이지 데이터 (results_region/{지역id}.json)와 첫 화면·API용 요약 (results_region/summary.json).

페이지 데이터는 서울 지도(map/template.html)와 같은 형태라 같은 템플릿으로 그린다: 맨 위 지역 하나 + 시군구(level "gu").
요약에는 공개 여부(region_v3.py의 공개 기준)와 최신 점수를 담는다. 공개 기준에 못 미친 지역도 페이지 데이터는 만들지만
사이트에는 올리지 않는다 (site_build.py).
"""
import json

import numpy as np
import pandas as pd

import backtest as bt
import region_supply as RS
import v3
from regions import REGIONS, josa, sub_word

RV = pd.read_pickle(bt.ROOT / "results_region" / "region_v3.pkl")
RC = pd.read_pickle(bt.ROOT / "results_region" / "region_calc.pkl")
OUT = bt.ROOT / "results_region"
seoul = pd.read_pickle(bt.ROOT / "results_v2" / "v3_seoul.pkl")
VM = seoul["vote_meta"]
raw = pd.read_csv(bt.ROOT / "data" / "indicators.csv", index_col=0, parse_dates=True)
raw = raw[raw.index <= raw["__price"].last_valid_index()]
idx = raw.index[raw.index >= "2006-01-01"]
r1 = lambda v: None if v is None or pd.isna(v) else round(float(v), 1)
r3 = lambda v: None if v is None or pd.isna(v) else round(float(v), 3)
ser = lambda s: [r1(v) for v in s.reindex(idx)]
f2 = lambda v: "–" if v is None or pd.isna(v) else f"{v:.2f}"
ym = lambda t: f"{t.year}년 {t.month}월"
LORO_START = pd.Timestamp("2011-02-01")  # 교차검증 성적은 늘 이 달부터 잼 (region_engine_study.OFF)
HAI_NAME = {"gyeonggi": "경기", "incheon": "수도권"}
AUX_LABEL = {"설문_가격전망": "KB 매매가격 전망 (2013~)", "설문_부동산원매매수급": "부동산원 매매수급 (2012~)",
             "전세_가격전망": "KB 전세가격 전망 (2016~)", "전세_부동산원전세수급": "부동산원 전세수급 (2012~)",
             "거래_2030비중": "20·30대 매수 비중 (2019~)", "청약_1순위경쟁률": "청약 1순위 경쟁률 (2020~)",
             "청약_미달역수": "청약 미달이 적을수록 (2020~)", "청약_무순위경쟁률": "무순위 줍줍 경쟁률 (2021~)",
             "청약_실제공급": "실제 분양 공급 (2021~)", "설문_주택가격전망CSI": "한국은행 주택가격전망 CSI (2013~, 전국)"}


def own_votes(own, vm):
    own = set(own)
    return int(sum(any(c in own for c in comp.split(", ")) for comp in vm["구성"]))


def weights(rid):
    """이 지역에 쓰는 표 비중: 고정 엔진 비중 + 이 지역에만 더한 공급 표 (region_supply.py, 대구). 비중이 없는 엔진이면 None."""
    w = (ENG or {}).get("weights")
    if not w:
        return None
    ex = ((ENG.get("extra") or {}).get(rid) or {}).get(RS.COL)
    return {**w, RS.COL: ex} if ex else dict(w)


def own_weight(own, vm, rid):
    """고정 엔진의 비중 중 시군구 자기 값을 쓰는 표의 몫 (비중이 없는 엔진이면 None). 공급 표는 시도 값이라 분모에만 들어간다."""
    w = weights(rid)
    if not w:
        return None
    own = set(own)
    mine = [v for v, comp in zip(vm.index, vm["구성"]) if any(c in own for c in comp.split(", "))]
    tot = sum(x for x in w.values() if x > 0)
    return sum(max(w.get(v, 0), 0) for v in mine) / tot if tot else None


def write(p, text):
    """중간에 끊겨도 반쯤 쓴 파일이 남지 않게 (임시 파일에 쓰고 바꿔 넣음)."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(p)


def pack(r, rs, y, level, weight=None):
    out = {"level": level, "gus": [], "score": ser(r["final"]), "speed": {k: ser(v) for k, v in r["groups"].items()},
           "themes": {k: ser(v) for k, v in r["themes"].items()},
           "rs": [r3(v) for v in rs.reindex(idx)] if rs is not None else [None] * len(idx),
           "fwd12": [r3(v) for v in y.reindex(idx)] if y is not None else [None] * len(idx), "weight": weight}
    if level != "gu" and r["aux"] is not None:
        out["aux"] = {c: ser(r["aux"][c]) for c in AUX_LABEL if c in r["aux"].columns and r["aux"][c].notna().any()}
    return out


def short(name):
    return name.split(" ")[-1] if " " in name else name


summary = {}
ENG = RV.get("engine")  # region_v3가 쓴 고정 엔진 (없으면 서울과 같은 v3)
IND_META = pd.read_csv(bt.ROOT / "data" / "indicator_meta.csv", index_col=0).fillna("")
VOTE_LABEL = {v3.GOOGLE: "구글 검색량 급증", RS.COL: "2~3년 전 착공 물량"}  # 여러 지표를 묶은 표라 indicator_meta.csv에 줄이 없는 것


def label(k, rid=None):
    """표 설명. 지역 페이지에서는 그 지역 값을 쓰는 표의 '서울'을 지역 이름으로 (PIR은 전국, 구매력은 KB 묶음 지역)."""
    s = IND_META.loc[k, "설명"].split(" (")[0] if k in IND_META.index else VOTE_LABEL.get(k, k)
    if rid is None or "서울" not in s:
        return s
    if k == "부담_PIR":
        return s.replace("서울", "전국")
    return s.replace("서울", HAI_NAME.get(rid, "6개광역시") if k == "부담_구매력역수" else REGIONS[rid]["name"])


def engine_note(rid):
    """지역 페이지 '계산 방식'의 엔진 설명."""
    if not ENG:
        return "서울과 같은 엔진이에요. ", "선행·동행·후행 3그룹을 같은 비중으로 평균해요. "
    n = len(ENG["regions"])
    head = (f"서울 밖 {n}개 지역에 같은 엔진을 써요('{ENG['name']}', {ENG['chosen']} {'임시 ' if ENG.get('provisional') else ''}고정). "
            f"미리 정한 규칙에 따라 후보 44개 중 {n}개 지역의 평균 성적이 가장 높은 엔진을 골랐고, 공개 여부는 한 지역씩 빼고 고른 엔진을 "
            "뺀 지역에 써서 잰 성적으로 정했어요. "
            + ("부산·경기 실거래가 다 들어오면 7개 지역으로 다시 골라 최종으로 고정해요. " if ENG.get("provisional") else ""))
    if ENG.get("weights"):
        w = weights(rid)  # 공급 보정 지역은 그 표까지 넣어 순위·몫을 잰다
        top = sorted(((v, k) for k, v in w.items() if v > 0), reverse=True)[:6]
        tw = sum(v for v, _ in top) / sum(v for v in w.values() if v > 0)
        names = ", ".join(label(k, rid) for _, k in top)
        how = (f"표마다 비중을 두고 합치는데, 비중은 {len(ENG['regions'])}개 지역에서 각 표가 이후 12개월 가격과 맞은 정도(순위상관, 맞지 않은 표는 0)로 정해 고정했어요. "
               f"비중이 큰 표는 {names}이고 이 여섯 표가 비중의 {tw * 100:.0f}%예요. ")
    else:
        how = f"{'·'.join(ENG['drop']) + ' 표는 빼고, ' if ENG['drop'] else ''}{ {'speed': '속도 3그룹', 'flat': '표마다', 'theme': '주제마다'}[ENG['agg']]} 같은 비중으로 합쳐요. "
    return head, how


ST = json.loads((OUT / "engine_study.json").read_text()) if (OUT / "engine_study.json").exists() else {}
HONEST = ST.get("honest", {})  # 2018년까지의 자료로만 비중을 배워 2019년 이후에 쓴 성적 (region_engine_study.py)
ENG_LABEL = f"지역 엔진 {ENG['chosen']}{' 임시' if ENG.get('provisional') else ''}" if ENG else v3.VERSION  # 서울 엔진(v3.x)과 구분
for rid, R in RV["regions"].items():
    VMr = R["vote_meta"]  # 이 지역 엔진의 표 구성
    d = REGIONS[rid]
    name, sw = d["name"], sub_word(rid)
    ENG_HEAD, ENG_HOW = engine_note(rid)
    ex = ((ENG or {}).get("extra") or {}).get(rid)
    n_extra = 1 if ex else 0  # 이 지역에만 더한 표 수 (표 수·지표 수 문구에 넣음)
    if ex:  # 공급 보정 (region_supply.py): 이 지역에만 더한 표를 숨기지 않고 밝힌다
        w = weights(rid)
        rank = sorted(w.values(), reverse=True).index(ex[RS.COL]) + 1
        o = RC["regions"][rid]
        v, y = RS.vote(o["ind"]), o["fwd12"].reindex(o["ind"].index)
        n_train = int(((v.index >= RS.OFF) & (v.index < RS.TRAIN_END) & v.notna() & y.notna()).sum())
        hb, hh = ST.get("honest_base", {}).get(rid), HONEST.get(rid)
        ENG_HOW += (f"{name}에는 표 하나를 더해요: 2~3년 전 착공 물량(국토부 주택착공실적, 아파트 재고 대비)이 적을수록 탐욕 쪽이에요. "
                    f"{name}{josa(name, '은', '는')} 공급이 유난히 많았던 곳이라({ex['chosen']} 결정), 이 표의 비중({ex[RS.COL]:.2f})은 {name} 자료로 2018년까지 배워 고정했어요. "
                    f"착공 표가 점수를 내기 시작한 뒤 {n_train}개월로 정한 값인데, {name} 표 중 비중이 {'가장 커요' if rank == 1 else f'{rank}번째로 커요'}"
                    f"(전체의 {ex[RS.COL] / sum(x for x in w.values() if x > 0) * 100:.0f}%). "
                    f"{name} 성적이 낮은 걸 본 뒤 더한 보정이라, 2018년까지 배운 비중으로 2019년 이후를 잰 성적으로 확인했어요"
                    + (f"(보정 전 {f2(hb['acc'])} → 후 {f2(hh['acc'])}). " if hb and hh else ". "))
    geo_src = json.loads((bt.ROOT / "data" / "region_maps" / f"{rid}.json").read_text())
    subs = [l for l in d["lawd"] if l in RV["subs"]]
    names = {l: d["lawd"][l] for l in subs}
    W = RC["regions"][rid]["sub_weight"].reindex(idx)
    Wn = W.div(W.sum(axis=1), axis=0)
    regions = {name: pack(R, R["rs"], R["fwd12"], "top", 1.0)}
    regions[name]["gus"] = [names[l] for l in subs]
    acc_sub, accs = {}, []
    st = R["start"]
    for l in subs:
        S = RV["subs"][l]
        wl = Wn[l].dropna() if l in Wn.columns else pd.Series(dtype=float)
        pk = pack(S, S["rs"], S["fwd12"], "gu", r3(wl.iloc[-1]) if len(wl) else None)
        pk["own_votes"] = own_votes(S["own"], VMr)
        own_w = own_weight(S["own"], VMr, rid)
        pk["n_trades"] = int(S["n_trades"])
        a = S["acc3"]
        if S["rs"] is None or pd.isna(a["sub"]):
            acc_sub[names[l]] = f"{names[l]}{josa(names[l], '은', '는')} 거래가 적어 정확도를 재지 못했어요. 점수는 KB·부동산원 시군구 값과 {name} 값으로 계산했어요."
        else:
            accs.append(a)
            acc_sub[names[l]] = (f"{ym(st)} 이후 이 {sw} 지수와 점수가 발표된 달부터 12개월 {names[l]} 실거래 가격의 순위상관은 {f2(a['sub'])}예요. "
                                 f"같은 기간 {name} 지수를 쓰면 {f2(a['region'])}, 서울 지수를 쓰면 {f2(a['seoul'])}예요. "
                                 f"{len(VMr) + n_extra}표 중 {pk['own_votes']}표만 이 {sw} 값이고"
                                 + (f"(비중으로는 {own_w * 100:.0f}%)" if own_w is not None else "")
                                 + f" 나머지는 {name} 값이라, 5점 미만 차이는 의미 있는 차이로 보기 어려워요."
                                 + (" 표 비중은 이 지역 자료도 함께 써서 정해서, 이 숫자는 조금 낙관적이에요." if ENG and ENG.get("weights") else ""))
        regions[names[l]] = pk
    A = pd.DataFrame(accs)
    mean = {k: (float(A[k].mean()) if len(A) else np.nan) for k in ("sub", "region", "seoul")}
    lo = R.get("loro")
    if lo:  # 고정 엔진: 이 지역을 빼고 고른 엔진으로 잰 성적을 먼저 (공개 판단에 쓴 값)
        h = HONEST.get(rid)
        top_txt = (f"표 비중을 배울 때 {name}{josa(name)} 빼고 재면 {ym(LORO_START)} 이후 이 지수와 점수가 발표된 달부터 12개월 {name} 실거래 가격의 순위상관은 {f2(lo['acc'])}, "
                   f"5년씩 나눠 본 중앙값 {f2(lo['win_median'])}, 2019년 이후 {f2(lo['recent'])}예요. 지금 엔진으로 다시 재면 {f2(R['acc'])}인데, "
                   f"고를 때 {name} 자료도 함께 써서 조금 낙관적이에요. "
                   + (f"또 표 비중을 배운 기간과 성적을 잰 기간이 같아요. 2018년까지의 자료로만 비중을 배워 2019년 이후에 쓰면 순위상관 {f2(h['acc'])}, "
                      f"5년씩 나눠 본 중앙값 {f2(h['win_median'])}이에요. " if h else "")
                   + f"같은 기간 서울 지수를 그대로 쓰면 {f2(R['acc_seoul'])}, KB 매수우위지수 하나만 보면 {f2(R['acc_kb'])}예요.")
    else:
        top_txt = (f"{ym(st)} 이후 이 지수와 점수가 발표된 달부터 12개월 {name} 실거래 가격의 순위상관은 {f2(R['acc'])}예요. "
                   f"5년씩 나눠 보면 중앙값 {f2(R['win_median'])}, 가장 나빴던 구간 {f2(R['win_min'])}이에요. "
                   f"같은 기간 서울 지수를 {name}에 그대로 쓰면 {f2(R['acc_seoul'])}, KB 매수우위지수 하나만 보면 {f2(R['acc_kb'])}예요.")
    geo = {"w": geo_src["w"], "h": geo_src["h"], "zones": {}, "outline": geo_src["outline"], "river": None,
           "gu": {names[l]: {"d": geo_src["areas"][l]["d"], "label": geo_src["areas"][l]["label"]} for l in subs}}
    by_w = sorted(subs, key=lambda l: -(regions[names[l]]["weight"] or 0))
    hai = HAI_NAME.get(rid, "6개광역시")
    n_tr = RC["regions"][rid]["n_trades"]
    method = (f"{ENG_HEAD}2009년 이전부터 자료가 있는 지표 {int(sum(len(c.split(', ')) for c in VMr['구성']))}개를 같은 원자료끼리 묶어 "
              f"{len(VMr)}표로 만들고{f'(여기에 {name}만 공급 표 1개를 더해 {len(VMr) + n_extra}표)' if n_extra else ''}, {ENG_HOW}지표의 방향(높을수록 탐욕)은 서울과 같아요. 가격·설문·전세·전세가율은 KB {d['kb']} 값, "
              f"거래량·매입자 구성·수급·미분양은 부동산원 {name} 값, 신고가·급락 비중과 정답(반복매매지수)은 국토부 실거래 {n_tr:,}건으로 계산해요. "
              f"주택구매력은 KB {hai} 값, PIR은 전국 값, 금리·가계신용·검색량·주가·선도아파트50은 전국 공통 값이에요. "
              f"{sw} 지수는 가격·전세·전세가율(KB), 거래량·매입자 구성(부동산원), 실거래를 그 {sw} 값으로 바꾸고 나머지는 {name} 값을 써요. "
              f"각 지표는 과거 {(ENG or {}).get('window', 120)}개월 안에서의 백분위로 바꾸고, 지역 자료가 늦게 시작하는 지표는 서울 값으로 채우지 않아요.")
    data = {"dates": [t.strftime("%Y-%m") for t in idx], "regions": regions, "geo": geo, "theme_order": list(VMr["주제"].unique()),
            "aux_label": AUX_LABEL, "n_ind": int(sum(len(c.split(", ")) for c in VMr["구성"])) + n_extra, "n_votes": int(len(VMr)) + n_extra, "k": v3.K_REGION if ENG else v3.K,
            "k_note": f"표마다 비중을 둬서 합치는 지역 엔진은 원점수가 서울보다 넓게 퍼져서, 서울({v3.K}배)과 같은 기준(가장 극단적인 달이 0·100에 닿지 않는 가장 큰 배율)으로 {v3.K_REGION}배를 써요." if ENG else None,
            "gu_order": [names[l] for l in subs], "version": v3.VERSION, "official_start": st.strftime("%Y-%m"),
            "top": name, "top_full": f"{name} 전체", "sub_word": sw, "presets": [["2008-12", "금융위기"], ["2022-11", "금리 급등 후 급락"]],
            "eyebrow": f"{name} 아파트 · 공포탐욕지수 {ENG_LABEL} · {len(subs)}개 {sw}", "map_label": f"{name} {sw} 지도",
            "method": method, "acc_text": {"top": top_txt, "sub": acc_sub}, "minis": [name] + [names[l] for l in by_w[:5]],
            "short_name": {names[l]: short(names[l]) for l in subs}, "compact_pins": len(subs) > 16,
            "sub_acc_mean": {k: r3(v) for k, v in mean.items()}, "region_id": rid,
            "compose_label": "구성 (속도별 3그룹, 참고용: 점수는 표마다 비중을 둬서 합쳐요)" if (ENG or {}).get("weights") else None}
    write(OUT / f"{rid}.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    s = R["final"].reindex(idx)
    t = s.last_valid_index()
    i = idx.get_loc(t)
    acc_src = lo or R  # 고정 엔진이면 교차검증 성적 (공개 판단에 쓴 값)
    summary[rid] = {"name": name, "publish": bool(R["publish"]), "month": t.strftime("%Y-%m"), "score": r1(s[t]),
                    "prev": r1(s.iloc[i - 1]), "acc": r3(acc_src["acc"]), "win_median": r3(acc_src["win_median"]), "win_min": r3(acc_src["win_min"]),
                    "acc_seoul": r3(R["acc_seoul"]), "acc_kb": r3(R["acc_kb"]), "start": st.strftime("%Y-%m"),
                    "n_sub": len(subs), "sub_word": sw, "sub_acc_mean": {k: r3(v) for k, v in mean.items()},
                    "engine": ENG["chosen"] if ENG else "A", "cross_validated": bool(lo),
                    "extra": sorted(k for k in ((ENG or {}).get("extra") or {}).get(rid, {}) if k == RS.COL)}
    print(f"{name}: {summary[rid]['score']} ({summary[rid]['month']}) · {'공개' if R['publish'] else '검증 중'} · "
          f"시군구 평균 정확도 {f2(mean['sub'])} / 시도 지수 {f2(mean['region'])}")
write(OUT / "summary.json", json.dumps(summary, ensure_ascii=False, indent=1))
