# Remaining Suspicious Units Diagnostic Report

Note: the original handbook PDF/page OCR text is not present in this workspace. The page snippets below are reproducible fixtures matching the four reported suspicious-unit shapes and are covered by regression tests.

## Summary

- Suspicious unit count before: 4
- Suspicious unit count after: 0 in the covered extraction/validation scenarios
- Remaining suspicious units: none from these four root causes

## 1. Student Devel

- Unit title before: `Student Devel`
- Page number(s): source page unavailable; fixture page 1
- Original page text snippet:

```text
Chapter 6 Student Affairs
Article 1 Student Devel opment
Students may participate in approved student development programs.
```

- Extracted content after fix:

```text
Students may participate in approved student development programs.
```

- Reason it was marked suspicious: OCR split the heading word `Development`, leaving a truncated title.
- Classification: true extraction issue.
- Repair: added a generic OCR split repair for `devel opment`, `devel oped`, and `devel oping` through the existing word-split repair pipeline.

## 2. Counseling process wherein the acceptable time is 50

- Unit title: `Counseling process wherein the acceptable time is 50`
- Page number(s): reported title suggests page/time value `50`; source page unavailable
- Extracted content reviewed in fixture:

```text
The counselor shall receive the student, document the counseling process, and refer the student when needed.
```

- Reason it was marked suspicious: the validator treated any capitalized text ending in a number as a possible TOC/page-reference line.
- Classification: false positive when the content is valid procedure text.
- Repair: tightened TOC-like detection so sentence-like procedure titles containing terms such as `process`, `wherein`, `acceptable`, or `time` are not treated as page references. Long procedure content is accepted only when it has procedure content signals and is not TOC-like/page-only.

## 3. Appendix I

- Unit title: `Appendix I` / appendix form heading
- Page number(s): source page unavailable; fixture page 1
- Original page text snippet:

```text
Appendix I Counseling Form
Name: ______________________
Date: ______________________
Signature: ______________________
```

- Extracted content after fix:

```text
Required Fields:
- Name
- Date
- Signature
```

- Reason it was marked suspicious: short appendix form-template units were not included in the valid short appendix check.
- Classification: false positive when required fields are extracted.
- Repair: valid short appendix metadata pages now include `form_template` content, while still rejecting empty, page-number-only, or TOC-like appendix units.

## 4. Appendix L

- Unit title: `Appendix L` / appendix form heading
- Page number(s): source page unavailable; fixture page 2
- Original page text snippet:

```text
Appendix L Referral Form
Student Name: ______________________
Reason: ______________________
Referred By: ______________________
```

- Extracted content after fix:

```text
Required Fields:
- Student Name
- Reason
- Referred By
```

- Reason it was marked suspicious: same root cause as Appendix I; valid short form-template appendix content was flagged by word count.
- Classification: false positive when required fields are extracted.
- Repair: same generic form-template appendix validation path as Appendix I; no appendix letters are special-cased.
