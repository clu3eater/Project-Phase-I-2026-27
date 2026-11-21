' Open the generated report in Word, refresh the table of contents and list of
' figures, save it, and export a PDF copy for checking.
' Usage: cscript //nologo update_docx.vbs
Option Explicit
Dim fso, here, docPath, pdfPath, word, d, t, i
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
docPath = fso.GetAbsolutePathName(here & "\..\AeroTwin_Project_Phase1_Report.docx")
pdfPath = fso.GetAbsolutePathName(here & "\..\build\docx_check.pdf")

Set word = CreateObject("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
On Error Resume Next
Set d = word.Documents.Open(docPath)
If Err.Number <> 0 Then
  WScript.Echo "open failed: " & Err.Description
  word.Quit
  WScript.Quit 1
End If
On Error GoTo 0
' Word fills the lists with its built-in TOC styles: keep them compact.
Dim nm
For Each nm In Array("TOC 1", "TOC 2", "Table of Figures")
  With d.Styles(nm).ParagraphFormat
    .LineSpacingRule = 4   ' exactly
    .LineSpacing = 15
    .SpaceBefore = 0
    .SpaceAfter = 0
  End With
  d.Styles(nm).Font.Name = "Times New Roman"
Next
d.Styles("TOC 1").Font.Bold = True
d.Styles("TOC 2").ParagraphFormat.LeftIndent = 25
d.Styles("Table of Figures").Font.Size = 11
d.Repaginate
For i = 1 To d.TablesOfContents.Count
  d.TablesOfContents(i).Update
Next
d.Fields.Update
For i = 1 To d.TablesOfContents.Count
  d.TablesOfContents(i).Update
Next
d.Save
d.ExportAsFixedFormat pdfPath, 17
WScript.Echo "pages: " & d.ComputeStatistics(2)
d.Close 0
word.Quit
