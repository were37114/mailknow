#!/usr/bin/env python3
"""生成200条审批边界样本（4类各50条）"""

import json
import os


def generate_samples():
    samples = []

    # ── 1. 直接审批 (50条) ──
    direct_items = [
        ("请审批Q2采购预算", "pm@company.com", "Q2采购预算已整理完成，金额￥50,000，请审批"),
        ("服务器扩容申请审批", "ops@company.com", "线上服务器负载过高，需扩容3台，请审批"),
        ("差旅报销单审批", "team@company.com", "北京出差费用报销，共计￥8,500，请审批"),
        ("新员工入职审批", "hr@company.com", "张三已通过面试，请审批入职流程"),
        ("合同续签审批", "legal@company.com", "与供应商A的合同即将到期，请审批续签"),
        ("软件许可购买审批", "dev@company.com", "JetBrains全公司许可，年费￥120,000，请审批"),
        ("办公设备采购审批", "admin@company.com", "新工位需配置显示器和键盘，请审批采购"),
        ("培训预算申请审批", "team@company.com", "团队技术培训2人，预算￥15,000，请审批"),
        ("客户退款审批", "cs@company.com", "客户A申请退款￥3,200，请审批"),
        ("项目立项审批", "pm@company.com", "新项目MailMind立项，需审批启动"),
        ("加班申请审批", "dev@company.com", "本周六加班处理紧急Bug，请审批"),
        ("会议室改造预算审批", "admin@company.com", "5楼会议室改造，预估￥25,000，请审批"),
        ("市场活动费用审批", "marketing@company.com", "618促销活动费用申请，￥80,000，请审批"),
        ("供应商变更审批", "procurement@company.com", "供应商B替代供应商A，需审批变更"),
        ("权限开通审批", "it@company.com", "新员工张三需开通VPN权限，请审批"),
        ("年度体检安排审批", "hr@company.com", "2026年度员工体检，预算￥200/人，请审批"),
        ("代码仓库迁移审批", "dev@company.com", "从GitLab迁移至GitHub，需审批"),
        ("客户合同审批", "sales@company.com", "客户C的SaaS服务合同，金额￥200,000，请审批"),
        ("数据备份方案审批", "ops@company.com", "新数据备份方案审批，年费￥30,000"),
        ("假期审批", "team@company.com", "申请5月15日-5月19日年假，请审批"),
        ("服务器迁移审批", "ops@company.com", "从IDC迁移至云服务器，费用￥150,000，请审批"),
        ("团建费用审批", "hr@company.com", "部门团建活动，预算￥10,000，请审批"),
        ("测试环境扩容审批", "qa@company.com", "测试服务器需增加2台实例，请审批"),
        ("广告投放审批", "marketing@company.com", "百度搜索广告投放，预算￥50,000，请审批"),
        ("设备报废审批", "ops@company.com", "5台旧服务器报废处理，请审批"),
        ("外包服务审批", "pm@company.com", "UI设计外包，费用￥60,000，请审批"),
        ("合规审查审批", "legal@company.com", "数据合规审查需外部顾问，费用￥40,000"),
        ("安全审计报告审批", "security@company.com", "年度安全审计报告，请审阅批准"),
        ("专利申请审批", "rd@company.com", "新算法专利申请，费用￥20,000，请审批"),
        ("客户赠品审批", "sales@company.com", "VIP客户赠品预算￥5,000，请审批"),
        ("办公室租赁审批", "admin@company.com", "新办公室续租，年租金￥500,000，请审批"),
        ("API服务开通审批", "dev@company.com", "第三方API服务年费￥12,000，请审批"),
        ("技术选型审批", "cto@company.com", "前端框架从Vue迁移至React，请审批"),
        ("人事调整审批", "hr@company.com", "张三从研发部调至产品部，请审批"),
        ("投标审批", "bd@company.com", "政府项目投标，押金￥30,000，请审批"),
        ("物流合作审批", "procurement@company.com", "与物流公司D签订合作协议，请审批"),
        ("系统升级审批", "it@company.com", "ERP系统从V3升级至V4，请审批"),
        ("质量认证审批", "qa@company.com", "ISO9001认证续期，费用￥15,000，请审批"),
        ("财务月报签核", "finance@company.com", "4月财务月报请审批签发"),
        ("付款申请签字", "finance@company.com", "供应商E付款￥45,000请签字确认"),
        ("技术方案审核", "arch@company.com", "微服务架构方案请审核批准"),
        ("招聘需求批准", "hr@company.com", "高级工程师HC 2个请批准"),
        ("域名续费审批", "it@company.com", "公司域名续费10年，￥5,000，请审批"),
        ("产品发布确认", "pm@company.com", "V2.0版本发布请审批确认"),
        ("合同变更签核", "legal@company.com", "合同条款第3条变更请签核"),
        ("紧急采购审批", "ops@company.com", "生产环境硬件故障紧急采购￥25,000"),
        ("预算调整审核", "finance@company.com", "Q3预算从100万调整至120万，请审核"),
        ("远程办公批准", "hr@company.com", "张三远程办公3个月请批准"),
        ("账号开通审批", "procurement@company.com", "新供应商F采购平台账号开通，请审批"),
        ("印章使用签核", "admin@company.com", "合同盖章请审批"),
    ]
    for i, (subject, from_addr, content) in enumerate(direct_items):
        samples.append({
            "id": f"direct_{i+1:03d}",
            "description": f"直接审批 - {subject}",
            "email": {"subject": subject, "from_addr": from_addr, "to_addrs": ["user@company.com"], "cc_addrs": [], "content": content},
            "expected": {"is_approval": True, "approval_type": "direct"}
        })

    # ── 2. CC审批 (50条) ──
    cc_items = [
        ("FYI: 张三的合同审批请求", "pm@company.com", "请财务部门审批此合同，抄送知会"),
        ("FYI: 项目预算调整通知", "finance@company.com", "项目预算已调整至120万，抄送知会"),
        ("FYI: 审批进度更新", "system@company.com", "采购审批已流转至部门经理，抄送知会"),
        ("FYI: 新政策审批流转", "hr@company.com", "远程办公政策变更审批，抄送知会"),
        ("FYI: 年度预算方案", "cfo@company.com", "2026年度预算已提交审批，抄送知会"),
        ("FYI: 供应商合同审批", "procurement@company.com", "供应商G合同审批中，抄送知会"),
        ("FYI: 报销审批通知", "team@company.com", "差旅报销单已提交审批，抄送知会"),
        ("FYI: 加班审批抄送", "hr@company.com", "李四加班申请已审批通过，抄送知会"),
        ("FYI: 设备采购审批流转", "it@company.com", "笔记本电脑采购审批中，抄送知会"),
        ("FYI: 客户合同审批抄送", "sales@company.com", "客户H合同审批流程已启动，抄送知会"),
        ("FYI: 请假审批通知", "hr@company.com", "王五年假申请已批准，抄送知会"),
        ("FYI: 项目立项审批抄送", "pm@company.com", "新项目已通过立项审批，抄送知会"),
        ("FYI: 培训申请审批", "team@company.com", "技术培训申请已提交，抄送知会"),
        ("FYI: 服务器采购审批", "ops@company.com", "新服务器采购审批中，抄送知会"),
        ("FYI: 办公室装修审批", "admin@company.com", "5楼装修方案审批中，抄送知会"),
        ("FYI: 软件购买审批抄送", "design@company.com", "Figma企业版购买审批，抄送知会"),
        ("FYI: 市场活动审批通知", "marketing@company.com", "618活动方案审批中，抄送知会"),
        ("FYI: 差旅审批抄送", "team@company.com", "上海出差审批已流转，抄送知会"),
        ("FYI: 合同续签审批", "legal@company.com", "与供应商I的合同续签审批中，抄送知会"),
        ("FYI: 权限开通审批通知", "it@company.com", "VPN权限开通审批已通过，抄送知会"),
        ("FYI: 团建活动审批抄送", "hr@company.com", "部门团建方案审批中，抄送知会"),
        ("FYI: 广告投放审批", "marketing@company.com", "Google Ads投放审批已提交，抄送知会"),
        ("FYI: 外包审批通知", "pm@company.com", "UI设计外包审批已通过，抄送知会"),
        ("FYI: 合规审批抄送", "legal@company.com", "数据合规审查审批中，抄送知会"),
        ("FYI: 安全审计审批通知", "security@company.com", "安全审计报告审批流转，抄送知会"),
        ("FYI: 专利审批抄送", "rd@company.com", "新专利申请审批中，抄送知会"),
        ("FYI: 客户赠品审批", "sales@company.com", "VIP客户赠品审批通过，抄送知会"),
        ("FYI: 租赁审批通知", "admin@company.com", "办公室续租审批中，抄送知会"),
        ("FYI: API服务审批抄送", "dev@company.com", "第三方API审批已提交，抄送知会"),
        ("FYI: 技术选型审批通知", "cto@company.com", "框架迁移审批中，抄送知会"),
        ("FYI: 人事调整审批抄送", "hr@company.com", "人员调动审批已启动，抄送知会"),
        ("FYI: 投标审批通知", "bd@company.com", "政府项目投标审批中，抄送知会"),
        ("FYI: 物流审批抄送", "procurement@company.com", "物流合作审批已提交，抄送知会"),
        ("FYI: 系统升级审批通知", "it@company.com", "ERP升级审批中，抄送知会"),
        ("FYI: 认证审批抄送", "qa@company.com", "ISO认证续期审批中，抄送知会"),
        ("审批通知：月度财务", "finance@company.com", "月度财务报告审批流转，抄送知会"),
        ("审批通知：供应商变更", "procurement@company.com", "供应商J变更审批中，抄送知会"),
        ("审批流转：代码审查", "dev@company.com", "核心模块代码审查审批，抄送知会"),
        ("审批通知：数据备份", "ops@company.com", "备份方案审批已提交，抄送知会"),
        ("审批抄送：会议纪要", "admin@company.com", "管理层会议纪要审批，抄送知会"),
        ("审批通知：产品路线图", "pm@company.com", "H2产品路线图审批中，抄送知会"),
        ("审批抄送：安全策略", "security@company.com", "安全策略更新审批，抄送知会"),
        ("审批通知：云服务", "ops@company.com", "云服务续费审批已提交，抄送知会"),
        ("审批抄送：培训计划", "hr@company.com", "年度培训计划审批中，抄送知会"),
        ("审批通知：办公采购", "admin@company.com", "办公文具批量采购审批，抄送知会"),
        ("审批抄送：客户报价", "sales@company.com", "客户K报价审批已通过，抄送知会"),
        ("审批通知：迁移方案", "dev@company.com", "数据库迁移审批中，抄送知会"),
        ("审批抄送：费用分摊", "finance@company.com", "部门费用分摊审批流转，抄送知会"),
        ("审批通知：年度总结", "pm@company.com", "年度工作总结审批，抄送知会"),
        ("审批抄送：新办公区", "admin@company.com", "新办公区装修审批中，抄送知会"),
    ]
    for i, (subject, from_addr, content) in enumerate(cc_items):
        samples.append({
            "id": f"cc_{i+1:03d}",
            "description": f"CC审批 - {subject}",
            "email": {"subject": subject, "from_addr": from_addr, "to_addrs": ["approver@company.com"], "cc_addrs": ["user@company.com"], "content": content},
            "expected": {"is_approval": True, "approval_type": "cc", "confidence_max": 0.7}
        })

    # ── 3. 已完成通知 (50条) ──
    notif_items = [
        ("合同审批已通过", "system@company.com", "您提交的合同审批已通过，请查看附件"),
        ("采购申请已批准", "system@company.com", "采购申请单#12345已批准"),
        ("报销已审批", "finance@company.com", "差旅报销单已审批通过"),
        ("请假审批已通过", "hr@company.com", "您的年假申请已批准"),
        ("预算审批已完成", "cfo@company.com", "Q2预算审批已完成"),
        ("权限开通完成", "it@company.com", "VPN权限已开通，请查收"),
        ("加班申请已批准", "hr@company.com", "加班申请已审批通过"),
        ("培训申请已通过", "hr@company.com", "技术培训申请已批准"),
        ("差旅审批已通过", "manager@company.com", "上海出差审批已通过"),
        ("项目立项已批准", "pm@company.com", "新项目立项审批已通过"),
        ("设备采购已批准", "ops@company.com", "服务器采购已审批"),
        ("软件购买已通过", "design@company.com", "Figma企业版购买已批准"),
        ("团建审批已完成", "hr@company.com", "部门团建方案已通过"),
        ("广告审批已通过", "marketing@company.com", "Google Ads投放已批准"),
        ("外包审批已完成", "pm@company.com", "UI设计外包已审批"),
        ("合规审查已完成", "legal@company.com", "数据合规审查审批已通过"),
        ("安全审计已通过", "security@company.com", "安全审计报告已审批"),
        ("专利申请已批准", "rd@company.com", "新专利申请已通过"),
        ("客户赠品已审批", "sales@company.com", "VIP客户赠品审批已通过"),
        ("租赁审批已完成", "admin@company.com", "办公室续租已审批"),
        ("API审批已通过", "dev@company.com", "第三方API服务已批准"),
        ("技术选型已批准", "cto@company.com", "框架迁移方案已审批"),
        ("人事调整已完成", "hr@company.com", "人员调动审批已完成"),
        ("投标审批已通过", "bd@company.com", "政府项目投标已批准"),
        ("物流审批已完成", "procurement@company.com", "物流合作协议已审批"),
        ("系统升级已完成", "it@company.com", "ERP升级已审批通过"),
        ("认证审批已通过", "qa@company.com", "ISO认证续期已批准"),
        ("月报审批已完成", "finance@company.com", "月度财务报告已审批"),
        ("供应商变更已完成", "procurement@company.com", "供应商J变更审批已通过"),
        ("代码审查已通过", "dev@company.com", "核心模块代码审查已批准"),
        ("备份方案已审批", "ops@company.com", "数据备份方案已通过"),
        ("会议纪要已审批", "admin@company.com", "管理层会议纪要已批准"),
        ("路线图已通过", "pm@company.com", "H2产品路线图已审批"),
        ("安全策略已批准", "security@company.com", "安全策略更新已通过"),
        ("云服务已审批", "ops@company.com", "云服务续费已批准"),
        ("培训计划已通过", "hr@company.com", "年度培训计划已审批"),
        ("办公采购已完成", "admin@company.com", "办公文具采购已审批"),
        ("客户报价已通过", "sales@company.com", "客户K报价已审批"),
        ("迁移方案已批准", "dev@company.com", "数据库迁移已审批"),
        ("费用分摊已完成", "finance@company.com", "部门费用分摊已审批"),
        ("合同审批未通过", "system@company.com", "合同审批因条款问题未通过"),
        ("采购申请已驳回", "finance@company.com", "采购申请超出预算已驳回"),
        ("报销审批已拒绝", "finance@company.com", "报销单据不完整已拒绝"),
        ("请假申请已驳回", "hr@company.com", "请假时间冲突已驳回"),
        ("加班申请未批准", "manager@company.com", "加班理由不充分未批准"),
        ("差旅审批已拒绝", "finance@company.com", "差旅预算超限已拒绝"),
        ("预算审批已驳回", "cfo@company.com", "预算超标已驳回"),
        ("审批已过期", "system@company.com", "审批超时未处理已自动关闭"),
        ("供应商变更已驳回", "procurement@company.com", "供应商资质不符已驳回"),
        ("外包审批未通过", "pm@company.com", "外包方案不完善未通过"),
    ]
    for i, (subject, from_addr, content) in enumerate(notif_items):
        samples.append({
            "id": f"notification_{i+1:03d}",
            "description": f"已完成通知 - {subject}",
            "email": {"subject": subject, "from_addr": from_addr, "to_addrs": ["user@company.com"], "cc_addrs": [], "content": content},
            "expected": {"is_approval": False, "approval_type": "notification"}
        })

    # ── 4. 系统转发审批 (50条) ──
    system_items = [
        ("采购审批单 #10001", "oa@company.com", "系统转发：请审批采购申请单#10001，金额￥5,000"),
        ("请假审批 #10002", "oa@company.com", "系统转发：张三请假3天，请审批"),
        ("报销审批 #10003", "oa@company.com", "系统转发：差旅报销￥3,200，请审批"),
        ("合同审批 #10004", "oa@company.com", "系统转发：供应商M合同审批，金额￥80,000"),
        ("权限审批 #10005", "oa@company.com", "系统转发：新员工VPN权限开通审批"),
        ("加班审批 #10006", "oa@company.com", "系统转发：王五周末加班审批"),
        ("预算审批 #10007", "oa@company.com", "系统转发：Q3预算调整审批，增量￥200,000"),
        ("采购审批单 #10008", "oa@company.com", "系统转发：办公设备采购￥12,000"),
        ("差旅审批 #10009", "oa@company.com", "系统转发：深圳出差审批，预算￥6,000"),
        ("培训审批 #10010", "oa@company.com", "系统转发：AWS认证培训审批，费用￥8,000"),
        ("请假审批 #10011", "oa@company.com", "系统转发：李四年假5天审批"),
        ("合同审批 #10012", "oa@company.com", "系统转发：客户N服务合同￥150,000"),
        ("报销审批 #10013", "oa@company.com", "系统转发：招待客户费用￥2,500"),
        ("采购审批单 #10014", "oa@company.com", "系统转发：开发机器采购￥35,000"),
        ("权限审批 #10015", "oa@company.com", "系统转发：生产环境权限开通审批"),
        ("加班审批 #10016", "oa@company.com", "系统转发：紧急Bug修复加班审批"),
        ("预算审批 #10017", "oa@company.com", "系统转发：市场活动追加预算￥40,000"),
        ("采购审批单 #10018", "oa@company.com", "系统转发：安全设备采购￥55,000"),
        ("差旅审批 #10019", "oa@company.com", "系统转发：广州出差审批，预算￥4,500"),
        ("培训审批 #10020", "oa@company.com", "系统转发：管理培训审批，费用￥12,000"),
        ("请假审批 #10021", "oa@company.com", "系统转发：赵六病假2天审批"),
        ("合同审批 #10022", "oa@company.com", "系统转发：外包服务合同￥200,000"),
        ("报销审批 #10023", "oa@company.com", "系统转发：团队聚餐费用￥1,800"),
        ("采购审批单 #10024", "oa@company.com", "系统转发：测试设备采购￥18,000"),
        ("权限审批 #10025", "oa@company.com", "系统转发：数据库只读权限开通审批"),
        ("加班审批 #10026", "oa@company.com", "系统转发：版本发布加班审批"),
        ("预算审批 #10027", "oa@company.com", "系统转发：研发工具追加预算￥25,000"),
        ("采购审批单 #10028", "oa@company.com", "系统转发：网络设备采购￥70,000"),
        ("差旅审批 #10029", "oa@company.com", "系统转发：成都出差审批，预算￥5,500"),
        ("培训审批 #10030", "oa@company.com", "系统转发：安全培训审批，费用￥3,000"),
        ("请假审批 #10031", "oa@company.com", "系统转发：孙七调休1天审批"),
        ("合同审批 #10032", "oa@company.com", "系统转发：云服务合同￥300,000"),
        ("报销审批 #10033", "oa@company.com", "系统转发：交通补贴报销￥800"),
        ("采购审批单 #10034", "oa@company.com", "系统转发：办公家具采购￥22,000"),
        ("权限审批 #10035", "oa@company.com", "系统转发：测试环境管理员权限审批"),
        ("加班审批 #10036", "oa@company.com", "系统转发：性能优化加班审批"),
        ("预算审批 #10037", "oa@company.com", "系统转发：运维工具追加预算￥15,000"),
        ("采购审批单 #10038", "oa@company.com", "系统转发：监控设备采购￥28,000"),
        ("差旅审批 #10039", "oa@company.com", "系统转发：武汉出差审批，预算￥7,000"),
        ("培训审批 #10040", "oa@company.com", "系统转发：产品培训审批，费用￥5,000"),
        ("请假审批 #10041", "oa@company.com", "系统转发：周八事假1天审批"),
        ("合同审批 #10042", "oa@company.com", "系统转发：物流服务合同￥100,000"),
        ("报销审批 #10043", "oa@company.com", "系统转发：通讯费报销￥500"),
        ("采购审批单 #10044", "oa@company.com", "系统转发：开发工具采购￥9,000"),
        ("权限审批 #10045", "oa@company.com", "系统转发：GitHub组织权限审批"),
        ("加班审批 #10046", "oa@company.com", "系统转发：客户问题排查加班审批"),
        ("预算审批 #10047", "oa@company.com", "系统转发：人力资源追加预算￥50,000"),
        ("采购审批单 #10048", "oa@company.com", "系统转发：空调设备采购￥45,000"),
        ("差旅审批 #10049", "oa@company.com", "系统转发：南京出差审批，预算￥4,000"),
        ("培训审批 #10050", "oa@company.com", "系统转发：领导力培训审批，费用￥20,000"),
    ]
    for i, (subject, from_addr, content) in enumerate(system_items):
        samples.append({
            "id": f"system_forward_{i+1:03d}",
            "description": f"系统转发审批 - {subject}",
            "email": {"subject": subject, "from_addr": from_addr, "to_addrs": ["user@company.com"], "cc_addrs": [], "content": content},
            "expected": {"is_approval": True, "approval_type": "system_forward"}
        })

    return samples


if __name__ == "__main__":
    samples = generate_samples()
    output_path = os.path.join(os.path.dirname(__file__), "approval_samples.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"Generated {len(samples)} samples -> {output_path}")

    from collections import Counter
    types = Counter(s["expected"]["approval_type"] for s in samples)
    for t, c in sorted(types.items()):
        print(f"  {t}: {c}")
