# IRB Considerations for CaseLinker

## Quick Answer

**It depends on your circumstances.** Here's what you need to know:

### Likely **NOT Required** If:
- ✅ You're doing **independent research** (not affiliated with an institution)
- ✅ You're using **publicly available, de-identified data** (which you are)
- ✅ You're **not directly interacting with human subjects**
- ✅ You're **not collecting new data** from people
- ✅ The data is already **publicly released** by law enforcement agencies

### Likely **REQUIRED** If:
- ❌ You're affiliated with a **university or research institution**
- ❌ You plan to **publish in academic journals** or present at conferences
- ❌ Your institution has a policy requiring IRB review for all research
- ❌ You're receiving **funding** that requires IRB approval
- ❌ You're a **student** (even independent research may require IRB)

## Your Current Situation

Based on your codebase:

### ✅ **Favorable Factors:**
1. **Public Data Only**: You're using publicly available Arizona ICAC reports (2011-2014) and NCMEC reports that are already redacted and released for public consumption
2. **No PII**: Your README states "No PII was processed; all data was already in the public domain"
3. **Secondary Data Analysis**: You're analyzing existing case summaries, not collecting new data
4. **No Direct Human Subjects**: You're not interacting with victims, perpetrators, or anyone else

### ⚠️ **Potential Concerns:**
1. **Sensitive Topic**: Child exploitation is a sensitive research area
2. **Victim Data**: Even anonymized, you're analyzing data about victims (though from public reports)
3. **Institutional Affiliation**: If you're a student or affiliated researcher, your institution may require IRB review regardless

## IRB Requirements by Context

### Scenario 1: Independent Researcher (No Institution)
- **IRB Review**: Generally **NOT required**
- **Why**: IRBs typically only have jurisdiction over research conducted under their institution's auspices
- **However**: You should still follow ethical research practices:
  - Ensure data is truly public and de-identified
  - Consider data security and privacy
  - Be transparent about data sources
  - Consider potential harm from re-identification (though unlikely with your data)

### Scenario 2: University Student/Faculty
- **IRB Review**: **LIKELY REQUIRED**
- **Why**: Most universities require IRB review for any research, even if:
  - Using public data
  - Not directly interacting with subjects
  - Independent project
- **Action**: Contact your institution's IRB office

### Scenario 3: Research Organization Employee
- **IRB Review**: **LIKELY REQUIRED**
- **Why**: Research organizations typically have IRB policies
- **Action**: Check with your organization's research compliance office

### Scenario 4: Publishing/Presenting Findings
- **IRB Review**: **MAY BE REQUIRED** by journals/conferences
- **Why**: Many academic venues require IRB approval documentation
- **Action**: Check submission requirements for your target venues

## What IRB Would Likely Determine

If you do need IRB review, your project would likely qualify for:

### **Exempt Review** (Fastest, least burdensome)
- **Category**: Research involving secondary analysis of publicly available data
- **Criteria**: 
  - Data is publicly available
  - No identifiers are collected
  - No interaction with subjects
- **Timeline**: Usually 1-2 weeks for exempt determination

### **Expedited Review** (Possible if concerns about sensitive topic)
- **Category**: Minimal risk research involving sensitive topics
- **Timeline**: Usually 2-4 weeks

### **Full Board Review** (Unlikely for your project)
- Only if IRB determines there are significant risks or ethical concerns

## Recommendations

### 1. **If You're Independent:**
- ✅ **No IRB needed**, but:
  - Document that data is public and de-identified
  - Keep records of data sources
  - Consider creating a data use statement/ethics statement
  - Be transparent about methods in any publications

### 2. **If You're Institutionally Affiliated:**
- ✅ **Contact your IRB office** - they can provide a quick determination
- ✅ **Submit an exempt review request** - it's usually straightforward for public data
- ✅ **Document your data sources** - IRB will want to see where data came from

### 3. **For Publications:**
- ✅ Check journal/conference requirements
- ✅ Many venues accept "IRB exempt" or "public data analysis" statements
- ✅ Be prepared to provide IRB documentation if required

## Key Documentation to Prepare

If you need IRB review, prepare:

1. **Data Source Documentation**:
   - Links to public AZICAC reports
   - Links to NCMEC reports
   - Statement that data is publicly available and de-identified

2. **Research Protocol**:
   - What you're analyzing (case patterns, trends)
   - Methods (text extraction, feature extraction, analysis)
   - No direct human subjects interaction

3. **Data Handling**:
   - How data is stored (SQLite database)
   - Security measures
   - Who has access

4. **Risk Assessment**:
   - Low risk: Public data, no identifiers, no subject interaction
   - Potential benefit: Understanding patterns in child exploitation cases

## Ethical Considerations (Beyond IRB)

Even if IRB isn't required, consider:

1. **Data Security**: Ensure your database and deployments are secure
2. **Privacy**: Don't attempt to re-identify individuals
3. **Sensitivity**: Be mindful of the sensitive nature of the topic
4. **Transparency**: Clearly document data sources and methods
5. **Responsible Use**: Ensure research is used responsibly and ethically

## Next Steps

1. **Determine your status**: Are you independent or institutionally affiliated?
2. **Check requirements**: 
   - If affiliated: Contact your IRB office
   - If independent: Review ethical guidelines for independent research
   - If publishing: Check journal/conference requirements
3. **Document everything**: Keep records of data sources, methods, and decisions
4. **Consider consultation**: If unsure, consult with:
   - Your institution's IRB office
   - Research ethics committee
   - Academic advisor (if student)
   - Legal counsel (if concerned about liability)

## Resources

- **OHRP (Office for Human Research Protections)**: https://www.hhs.gov/ohrp/
- **CITI Program**: Research ethics training (often required by IRBs)
- **Your Institution's IRB**: Check their website for guidance

## Disclaimer

**This document is for informational purposes only and does not constitute legal or regulatory advice.** IRB requirements vary by:
- Institution
- Jurisdiction
- Type of research
- Funding sources

**Always consult with your institution's IRB office or research compliance office for definitive guidance.**

---

## Quick Checklist

- [ ] Am I affiliated with a university/research institution? → **Contact IRB**
- [ ] Am I a student? → **Contact IRB**
- [ ] Am I receiving research funding? → **Check funding requirements**
- [ ] Am I planning to publish? → **Check journal requirements**
- [ ] Am I truly independent? → **Likely no IRB needed, but document ethics**
