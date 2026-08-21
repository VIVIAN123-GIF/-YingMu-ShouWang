"""Build printable two-page consent forms for P01-P03."""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from scripts.build_final_documents import (
    BLUE,
    DARK_BLUE,
    EAST_ASIA_FONT,
    LATIN_FONT,
    LIGHT_BLUE,
    MUTED,
    _add_page_field,
    _set_cell_margins,
    _set_font,
    _set_table_geometry,
    _shade,
    load_profile,
)


PARTICIPANTS = ("P01", "P02", "P03")
CONTENT_WIDTH_DXA = 9800


def _set_repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    properties.append(marker)


def _paragraph(document: Document, text: str = "", *, bold: bool = False, size: float = 10.2,
               after: float = 4, align=None, color: str | None = None):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = 1.12
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run(text)
    _set_font(run, size=size, bold=bold, color=color)
    return paragraph


def _heading(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(7)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    _set_font(run, size=11.5, bold=True, color=BLUE)


def _checkbox(document: Document, text: str, *, required: bool = False) -> None:
    marker = "□"
    suffix = "（必选）" if required else ""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Mm(4)
    paragraph.paragraph_format.first_line_indent = Mm(-4)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.line_spacing = 1.08
    run = paragraph.add_run(f"{marker} {text}{suffix}")
    _set_font(run, size=9.8)


def _metadata_table(document: Document, participant_id: str, profile: dict[str, str]) -> None:
    rows = [
        ("参与者匿名编号", participant_id, "参与者真实姓名", "________________"),
        ("授权记录编号", f"AUTH-{participant_id}-________", "拍摄日期", "____年__月__日 / ____年__月__日"),
        ("学校与项目", f"{profile['school']} · 萤目守望", "项目负责人", f"{profile['contact_name']}  {profile['mobile']}"),
    ]
    table = document.add_table(rows=len(rows), cols=4)
    _set_table_geometry(table, [1650, 3250, 1650, 3250])
    for row_index, values in enumerate(rows):
        for column_index, value in enumerate(values):
            cell = table.cell(row_index, column_index)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell, top=100, bottom=100, start=120, end=120)
            if column_index % 2 == 0:
                _shade(cell._tc, LIGHT_BLUE)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.0
            run = paragraph.add_run(value)
            _set_font(run, size=9.1, bold=column_index % 2 == 0)


def _signature_table(document: Document) -> None:
    rows = [
        ("参与者签名", "________________", "日期", "____年__月__日"),
        ("实验负责人签名", "________________", "日期", "____年__月__日"),
        ("现场安全员签名", "________________", "日期", "____年__月__日"),
    ]
    table = document.add_table(rows=len(rows), cols=4)
    _set_table_geometry(table, [1750, 3150, 1200, 3700])
    for row_index, row in enumerate(table.rows):
        for index, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell, top=180, bottom=180, start=120, end=120)
            if index in {0, 2}:
                _shade(cell._tc, LIGHT_BLUE)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(rows[row_index][index])
            _set_font(run, size=9.5, bold=index in {0, 2})


def build_consent(participant_id: str, profile: dict[str, str], output: Path) -> None:
    document = Document()
    section = document.sections[0]
    # Named form override: A4 is used because the forms will be printed and signed in China.
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(14)
    section.right_margin = Mm(16)
    section.bottom_margin = Mm(14)
    section.left_margin = Mm(16)
    section.header_distance = Mm(7)
    section.footer_distance = Mm(7)

    normal = document.styles["Normal"]
    normal.font.name = LATIN_FONT
    normal.font.size = Pt(10.2)
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:ascii"), LATIN_FONT)
    fonts.set(qn("w:hAnsi"), LATIN_FONT)
    fonts.set(qn("w:eastAsia"), EAST_ASIA_FONT)

    header = section.header.paragraphs[0]
    header.text = f"吉林大学 · 萤目守望受控视频实验 · {participant_id}"
    _set_font(header.runs[0], size=8.5, color=MUTED)
    _add_page_field(section.footer.paragraphs[0])

    title = _paragraph(
        document,
        "“萤目守望”受控视频实验知情同意、肖像与数据授权书",
        bold=True,
        size=17,
        after=5,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        color=DARK_BLUE,
    )
    title.paragraph_format.keep_with_next = True
    _paragraph(
        document,
        "健康成年志愿者受控模拟 · 非医学研究 · 不实施真实跌倒",
        bold=True,
        size=10,
        after=7,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        color=BLUE,
    )
    _metadata_table(document, participant_id, profile)

    _heading(document, "一、项目说明")
    _paragraph(
        document,
        "本人自愿参加“萤目守望”居家安全预警系统工程验证。项目面向老年居家安全应用，但本次参与者为健康成年人。实验只验证工程可行性，不判断本人健康状况，不构成医学诊断或临床研究。",
    )

    _heading(document, "二、拍摄内容与时间")
    _paragraph(
        document,
        "本人计划在至少两个日期完成32段受控视频：8段正常基线、12段风险前兆模拟和12段正常控制；另完成约4小时正常活动稳定性记录。动作包括正常行走、坐下起身、停步转身、快速但可控起身、轻微受控摇晃、慢速小步和安全模拟单侧步幅变小。摄像机为固定机位萤石C6c。",
    )

    _heading(document, "三、可能采集的数据")
    _checkbox(document, "视频画面及其中的肖像、衣着、动作和居家背景。", required=True)
    _checkbox(document, "拍摄口令或环境中可能被设备录入的声音。", required=True)
    _checkbox(document, "MediaPipe 33点姿态、步态和躯干特征、时间戳、质量指标及系统输出。", required=True)
    _checkbox(document, "匿名编号、场景标签、光照、机位、有效性、排除原因和文件SHA-256。", required=True)

    _heading(document, "四、安全风险与停止条件")
    _paragraph(
        document,
        "实验不要求真实跌倒、闭眼行走、故意绊倒、失控转身或危险跛行。现场须使用防滑稳定座椅、清空路线，并安排镜头外安全员。本人出现头晕、疼痛、真实失衡、碰撞风险、疲劳或任何不适时，可以立即停止且不承担不利后果；该片段将标记为ABORTED。",
    )
    _paragraph(document, "参与者第一页简签：________________", bold=True, size=9.8, after=0, align=WD_ALIGN_PARAGRAPH.RIGHT)

    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    _heading(document, "五、授权用途")
    _checkbox(document, "同意项目团队将匿名统计、姿态特征、系统结果和脱敏截图用于研究报告、测试报告、系统文档和演示视频。", required=True)
    _checkbox(document, "同意赛事主办方、评委在本次评审及原始材料抽查中查看授权范围内的数据。", required=True)
    _checkbox(document, "同意将本签字扫描件附入07号验证设计PDF，作为仅赛事评审使用的受限附件；不得上传公开GitHub。", required=True)
    _checkbox(document, "同意项目团队在获得允许的范围内，为评审保存必要原始材料至约定期限。", required=True)

    _heading(document, "六、本人允许的画面展示形式（至少勾选一项）")
    _checkbox(document, "允许在赛事私密提交的演示视频中使用未模糊的原始肖像画面。")
    _checkbox(document, "只允许使用人脸和可识别私人信息已模糊的画面。")
    _checkbox(document, "只允许使用骨架、轮廓或无法识别本人身份的画面。")
    _paragraph(
        document,
        "未勾选的展示形式视为不同意。公开在线入口不托管本人的原始视频、签字扫描件或真实平台截图，仅展示脱敏模拟数据和汇总指标。",
        size=9.5,
    )

    _heading(document, "七、保存、保密与禁止用途")
    _paragraph(
        document,
        f"原始视频和签字文件存放在团队受控私有目录，不进入公开代码仓库。保存期限最迟至{profile['retention_until']}；到期安全删除，赛事尚未结束或需继续研究时必须重新取得书面授权。禁止将材料用于身份识别、商业广告、医学诊断或未经再次授权的公开传播。",
    )

    _heading(document, "八、撤回与已提交材料")
    _paragraph(
        document,
        "本人可在正式提交前书面撤回，团队将停止使用并删除对应材料。正式提交后，团队将停止后续使用并在可行范围内请求主办方删除，但不能承诺已进入评审流程、备份或依法留存的副本立即消除。撤回不影响撤回前已经完成的合法处理。",
    )

    _heading(document, "九、确认与签字")
    _checkbox(document, "本人已满18周岁，当前无头晕、急性伤病或其他不适合参与活动的情况。", required=True)
    _checkbox(document, "本人已阅读并理解本授权书，有机会提问，签署完全自愿。", required=True)
    _checkbox(document, "本人知晓可以拒绝任一非必选展示形式，并可随时要求停止拍摄。", required=True)
    _signature_table(document)
    _paragraph(
        document,
        "参与者应保留本授权书照片或副本。团队不得在未重新取得书面授权的情况下扩大用途。",
        size=8.8,
        after=0,
        color=MUTED,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )

    document.core_properties.title = f"萤目守望参与者授权书-{participant_id}"
    document.core_properties.author = "吉林大学萤目守望项目组"
    document.core_properties.subject = "受控视频实验知情同意、肖像与数据授权"
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=Path, default=Path("final-delivery/private-input/submission-profile.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/consent-forms/docx"))
    args = parser.parse_args()
    profile = load_profile(args.profile)
    for participant_id in PARTICIPANTS:
        output = args.output_dir / f"参与者授权书_{participant_id}.docx"
        build_consent(participant_id, profile, output)
        print(f"BUILT {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
