# Suspicious Units Diagnostic Report

Note: the original handbook PDF/page text is not present in this workspace. The snippets below are reproducible page-text fixtures matching the reported failure shapes, run through the current handbook extraction and validation path.

## Student Devel

- Original page text snippet:

```text
Chapter 6 Student Affairs
Article 1 Student Devel
opment
Students may participate in approved student development programs.
```

- Extracted unit title: `Student Development`
- Extracted content: `Students may participate in approved student development programs.`
- Reason it was marked suspicious: broken OCR heading wrap produced an incomplete title (`Student Devel`) and low-confidence/short content.
- Proposed classification: extraction issue, repaired generically by merging wrapped heading fragments before unit splitting.

## Thesis/Dissertation and Conduct of Thesis/Dissertation

- Original page text snippet:

```text
Chapter 5 Academic Policies
Article 14: Thesis/Dissertation and Conduct of Thesis/Dissertation
Writing
Graduate students shall comply with thesis and dissertation writing policies.
The manuscript adviser, panel, and college shall follow approved procedures.
```

- Extracted unit title: `Thesis/Dissertation and Conduct of Thesis/Dissertation Writing`
- Extracted content: full article body beginning `Graduate students shall comply...`
- Reason it was marked suspicious: final title word was split onto a separate OCR line and could be extracted as an incomplete/truncated unit.
- Proposed classification: extraction issue, repaired generically for short continuations of compound article/section headings.

## Minor Offense

- Original page text snippet:

```text
Chapter 7 Student Discipline
Article 1 Student Offenses
Minor Offense
- Warning
- Written reprimand
```

- Extracted unit title: `Minor Offense`
- Extracted content:

```text
- Warning
- Written reprimand
```

- Reason it was marked suspicious: valid disciplinary-rule units can be naturally short and were flagged solely by word count.
- Proposed classification: valid, when the short unit has disciplinary content such as sanctions, penalties, warnings, violations, or bullet sanctions.

## Curricular Offerings - College of Law

- Original page text snippet:

```text
Chapter 2 Curricular Offerings
College of Law
Juris Doctor
```

- Extracted unit title: `Curricular Offerings - College of Law`
- Extracted content:

```text
Programs:
- Juris Doctor
```

- Reason it was marked suspicious: `Juris Doctor` was not recognized as a degree-program line, so the listing could become too short or structurally incomplete.
- Proposed classification: extraction issue, repaired generically by recognizing common law degree names as degree programs.

## Curricular Offerings - College of Law, Sta Cruz Campus

- Original page text snippet:

```text
Chapter 2 Curricular Offerings
College of Law, Sta Cruz Campus
Juris Doctor
```

- Extracted unit title: `Curricular Offerings - College of Law`
- Extracted content:

```text
Campuses:
- Sta. Cruz

Programs:
- Juris Doctor
```

- Reason it was marked suspicious: singular `Campus` qualifiers were not stripped/stored correctly, and the law degree line was not recognized as a program.
- Proposed classification: extraction issue, repaired generically by handling `campus` and `campuses` availability phrases and law degree lines.
