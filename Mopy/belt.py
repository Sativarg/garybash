#===================================================
# Specific parser for Wrye Bash
#===================================================
import ScriptParser         # generic parser class
import wx
import wx.wizard as wiz     # wxPython wizard class
import bosh, balt
from bolt import _
import struct, string
import win32api
#---------------------------------------------------
gDialogSize = (600,440)
#---------------------------------------------------

#Translateable strings
EXTRA_ARGS =   _("Extra arguments to '%s'.")
MISSING_ARGS = _("Missing arguments to '%s'.")
UNEXPECTED =   _("Unexpected '%s'.")

def replaceShader(sdpFileName, shaderName, shaderFileName):
    temp = bosh.dirs['mods'].join('Shaders', sdpFileName+'.bak')
    sdp = bosh.dirs['mods'].join('Shaders', sdpFileName)
    sNew = bosh.dirs['mods'].join('Shaders', shaderFileName)
    sBak = bosh.dirs['mopy'].join('Data', 'Shaders Backup', sdpFileName, shaderName)

    if not sdp.exists() and not sdp.isfile(): return
    if not sNew.exists() and not sNew.isfile(): return
    if sBak.exists() and sBak.isfile():
        sBak.remove()

    sdp.moveTo(temp.s)        
    
    shaderFile = sNew.open('rb')
    newData = shaderFile.read()
    shaderFile.close()
    
    backupFile = sBak.open('wb')

    editShader(sdp, temp, shaderName, newData, backupFile)
    
def restoreShader(sdpFileName, shaderName):
    temp = bosh.dirs['mods'].join('Shaders', sdpFileName+'.bak')
    sdp = bosh.dirs['mods'].join('Shaders', sdpFileName)
    dBackup = bosh.dirs['mopy'].join('Data', 'Shaders Backup', sdpFileName)
    sNew = dBackup.join(shaderName)

    if not sdp.exists() and not sdp.isfile(): return
    if not sNew.exists() and not sNew.isfile(): return

    sdp.moveTo(temp.s)
    shaderFile = sNew.open('rb')
    newData = shaderFile.read()
    shaderFile.close()

    editShader(sdp, temp, shaderName, newData, None)
    sNew.remove()
    #Clean up dirs
    for path, dirs, files in dbackup.walk():
        if len(dirs) == 0 and len(files) == 0:
            path.removedirs()
        
def editShader(sdp, temp, shaderName, newData, backupFile):
    mtime = temp.getmtime()
    newSDP = sdp.open('wb')
    oldSDP = temp.open('rb')

    #Read some bytes
    newSDP.write(oldSDP.read(4))

    #Read the number of shaders
    numstr = oldSDP.read(4)
    (num,) = struct.unpack('l', numstr)
    newSDP.write(numstr)

    #Save position of the 'size' bytes
    sizeoffset = oldSDP.tell()
    newSDP.write(oldSDP.read(4))

    #Go through each shader
    bFound = False
    for i in range(num):
        name = oldSDP.read(0x100)
        newSDP.write(name)
        sizestr = oldSDP.read(4)
        (size,) = struct.unpack('l', sizestr)
        data = oldSDP.read(size)

        #See if it's the right one
        if not bFound:
            #shader names are stored as 256 character null-terminated strings,
            #python strings aren't null-terminated so...
            sname = string.lower(name[:string.find(name, '\0')])

            if sname == string.lower(shaderName):
                newSDP.write(struct.pack('l', len(newData)))
                newSDP.write(newData)
                bFound = True

                if backupFile:            
                    backupFile.write(data)
                    backupFile.close()
                continue
        newSDP.write(sizestr)
        newSDP.write(data)
    # Now update the size value at the beginning of the file
    newSDP.seek(sizeoffset)
    size = sdp.size - 12
    newSDP.write(struct.pack('l', size))

    newSDP.close()
    oldSDP.close()
    temp.remove()    

    # Finally update the time stamps
    sdp.setmtime(mtime)
    
class WizardReturn(object):
    __slots__ = ('Canceled', 'SelectEspms', 'SelectSubPackages', 'Install')

    def __init__(self):
        self.Canceled = False
        self.SelectEspms = []
        self.SelectSubPackages = []
        self.Install = False

# InstallerWizard ----------------------------------
#  Class used by Wrye Bash, creates a wx Wizard that
#  dynamically creates pages based on a script
#---------------------------------------------------
class InstallerWizard(wiz.Wizard):
    def __init__(self, link, subs):
        wiz.Wizard.__init__(self, link.gTank, -1, _('Installer Wizard'))
        #Hide the "Previous" button, we wont use it
        self.FindWindowById(wx.ID_BACKWARD).Hide()

        #'dummy' page tricks the wizard into always showing the "Next" button,
        #'next' will be set by the parser
        self.dummy = wiz.PyWizardPage(self)
        self.next = None

        #True prevents actually moving to the 'next' page.  We use this after the "Next"
        #button is pressed, while the parser is running to return the _actual_ next page
        #'finishing' is to allow the "Next" button to be used when it's name is changed to
        #'Finish' on the last page of the wizard
        self.blockChange = True
        self.finishing = False

        #parser that will spit out the pages
        path = link.selected[0]
        installer = link.data[path]
        bArchive = link.isSingleArchive()
        if bArchive:
            installer.unpackToTemp(path, [installer.hasWizard])
            self.wizard_file = installer.tempDir.join(installer.hasWizard)
        else:
            self.wizard_file = link.data.dir.join(path.s, installer.hasWizard)
        self.parser = WryeParser(self, installer, subs, bArchive, path, link.bAuto)

        #Intercept the changing event so we can implement 'blockChange'        
        self.Bind(wiz.EVT_WIZARD_PAGE_CHANGING, self.OnChange)
        self.ret = WizardReturn()

        #Set the size for the wizard to use
        self.SetPageSize(gDialogSize)

    def HasPrevPage(self): return False

    def OnChange(self, event):
        if not self.finishing:
            if event.GetDirection():
                if self.blockChange:
                    #Tell the current page that next was pressed,
                    #So the parser can continue parsing,
                    #Then show the page that the parser returns,
                    #rather than the dummy page
                    event.GetPage().OnNext()
                    event.Veto()
                    self.next = self.parser.Continue()
                    self.blockChange = False
                    self.ShowPage(self.next)
                else:
                    self.blockChange = True
            else:
                event.Veto()

    def Run(self):
        page = self.parser.Begin(self.wizard_file)
        if page:
            self.ret.Canceled = not self.RunWizard(page)
        return self.ret
#End of Installer Wizard

# PageInstaller ----------------------------------------------
#  base class for all the parser wizard pages, just to handle
#  a couple simple things here
#-------------------------------------------------------------
class PageInstaller(wiz.PyWizardPage):
    def __init__(self, parent):
        wiz.PyWizardPage.__init__(self, parent)
        self.parent = parent

    def GetNext(self): return self.parent.dummy
    def GetPrev(self): return None
    def OnNext(self):
        #This is what needs to be implemented by sub-classes,
        #this is where flow control objects etc should be
        #created
        pass
# End PageInstaller ------------------------------------------

# PageError --------------------------------------------------
#  Page that shows an error message, hase only a "Cancel"
#  button enabled, and cancels any changes made
#-------------------------------------------------------------
class PageError(PageInstaller):
    def __init__(self, parent, title, errorMsg):
        PageInstaller.__init__(self, parent)

        #Disable the "Finish"/"Next" button        
        self.parent.FindWindowById(wx.ID_FORWARD).Enable(False)

        #Layout stuff
        sizerMain = wx.FlexGridSizer(2, 1, 5, 5)
        textError = wx.TextCtrl(self, -1, errorMsg, style=wx.TE_READONLY|wx.TE_MULTILINE)
        sizerMain.Add(wx.StaticText(self, -1, title))
        sizerMain.Add(textError, 0, wx.ALL|wx.CENTER|wx.EXPAND)
        sizerMain.AddGrowableCol(0)
        sizerMain.AddGrowableRow(1)
        self.SetSizer(sizerMain)
        self.Layout()

    def GetNext(self): return None        
# End PageError ----------------------------------------------

# PageSelect -------------------------------------------------
#  A Page that shows a message up top, with a selection box on
#  the left (multi- or single- selection), with an optional
#  associated image and description for each option, shown when
#  that item is selected
#-------------------------------------------------------------
class PageSelect(PageInstaller):
    def __init__(self, parent, bMany, title, desc, listItems, listDescs, listImages, defaultMap):
        PageInstaller.__init__(self, parent)
        self.items = listItems
        self.images = listImages
        self.descs = listDescs
        self.bMany = bMany
        self.bmp = wx.EmptyBitmap(1, 1)
        self.index = None

        sizerMain = wx.FlexGridSizer(4, 1, 5, 0)

        sizerTitle = wx.StaticBoxSizer(wx.StaticBox(self, -1, ''))
        self.TitleDesc = wx.StaticText(self, -1, desc)
        sizerTitle.Add(self.TitleDesc, 0, wx.ALIGN_CENTER|wx.ALL)
        sizerMain.Add(sizerTitle, 0, wx.EXPAND)

        sizerBoxes = wx.FlexGridSizer(2, 2, 5, 5)
        sizerBoxes.Add(wx.StaticText(self, -1, _('Options:')))
        sizerBoxes.AddStretchSpacer()
        self.textItem = wx.TextCtrl(self, -1, '', style=wx.TE_READONLY|wx.TE_MULTILINE)        
        self.bmpItem = wx.StaticBitmap(self, -1, wx.NullBitmap, size=(200, 200))
        if bMany:
            self.listOptions = wx.CheckListBox(self, 643, choices=listItems)
            for index, default in enumerate(defaultMap):
                self.listOptions.Check(index, default)
        else:
            self.listOptions = wx.ListBox(self, 643, choices=listItems)
            for index, default in enumerate(defaultMap):
                if default:
                    self.listOptions.Select(index)
                    self.Selection(index)
                    break
        sizerBoxes.Add(self.listOptions, 0, wx.ALL|wx.EXPAND)
        sizerBoxes.Add(self.bmpItem, 0, wx.ALL|wx.EXPAND)
        sizerBoxes.AddGrowableRow(1)
        sizerBoxes.AddGrowableCol(0)
        sizerBoxes.AddGrowableCol(1)
        sizerMain.Add(sizerBoxes, -1, wx.EXPAND)

        sizerMain.Add(wx.StaticText(self, -1, _('Description:')))
        sizerMain.Add(self.textItem, -1, wx.EXPAND|wx.ALL)

        self.SetSizer(sizerMain)
        sizerMain.AddGrowableRow(3)
        sizerMain.AddGrowableCol(0)
        self.Layout()

        wx.EVT_LISTBOX(self, 643, self.OnSelect)
        self.bmpItem.Bind(wx.EVT_LEFT_DCLICK, self.OnDoubleClick)
        self.bmpItem.Bind(wx.EVT_MIDDLE_UP, self.OnDoubleClick)

    def OnSelect(self, event):
        index = event.GetSelection()
        self.Selection(index)

    def OnDoubleClick(self, event):
        try:
            file = self.images[self.index]
            if file.exists() and not file.isdir():
                file.start()
        except:
            pass
        

    def Selection(self, index):
        self.index = index
        self.textItem.SetValue(self.descs[index])
        file = self.images[index]
        if file.exists() and not file.isdir():
            image = wx.Image( file.s )
            factor = 400.0 / max(image.GetHeight(), image.GetWidth())
            newHeight = round(image.GetHeight() * factor)
            newWidth = round(image.GetWidth() * factor)
            image.Rescale(newWidth, newHeight)
            self.bmp = wx.BitmapFromImage(image)
            self.bmpItem.SetBitmap(self.bmp)
        else:
            self.bmpItem.SetBitmap(wx.NullBitmap)
        self.Layout()

    def OnNext(self):
        temp = []
        if self.bMany:
            index = -1
            for item in self.items:
                index += 1
                if self.listOptions.IsChecked(index):
                    temp.append(item)
        else:
            for i in self.listOptions.GetSelections():
                temp.append(self.items[i])
        self.parent.parser.PushFlow('Select', False, ['SelectOne', 'SelectMany', 'Case', 'Default', 'EndSelect'], values=temp, hitCase=False)
# End PageSelect -----------------------------------------

# PageFinish ---------------------------------------------
#  Page displayed at the end of a wizard, showing which
#  sub-packages and which esps and espms will be
#  selected.  Also displays some notes for the user
#---------------------------------------------------------
class PageFinish(PageInstaller):
    def __init__(self, parent, subsList, espmsList, bAuto, notes):
        PageInstaller.__init__(self, parent)

        subs = subsList.keys()
        subs.sort(lambda l,r: cmp(l, r))
        espms = espmsList.keys()
        espms.sort(lambda l,r: cmp(l, r))

        sizerMain = wx.FlexGridSizer(4, 1, 5, 0)

        sizerTitle = wx.StaticBoxSizer(wx.StaticBox(self, -1, ''))
        textTitle = wx.StaticText(self, -1, _("The installer script has finished, and selected the following sub-packages, esps, and esms to be installed."))
        textTitle.Wrap(gDialogSize[0]-10)
        sizerTitle.Add(textTitle, 0, wx.ALIGN_CENTER|wx.ALL)
        sizerMain.Add(sizerTitle, 0, wx.EXPAND)

        sizerLists = wx.FlexGridSizer(2, 2, 5, 5)
        sizerLists.Add(wx.StaticText(self, -1, _('Sub-Packages')))
        sizerLists.Add(wx.StaticText(self, -1, _('Esp/ms')))
        self.listSubs = wx.CheckListBox(self, 666, choices=subs)
        wx.EVT_CHECKLISTBOX(self, 666, self.OnSelectSubs)
        for index,key in enumerate(subs):
            if subsList[key]:
                self.listSubs.Check(index, True)
                self.parent.ret.SelectSubPackages.append(key)
        self.listEspms = wx.CheckListBox(self, 667, choices=espms)
        wx.EVT_CHECKLISTBOX(self, 667, self.OnSelectEspms)
        for index,key in enumerate(espms):
            if espmsList[key]:
                self.listEspms.Check(index, True)
                self.parent.ret.SelectEspms.append(key)
        sizerLists.Add(self.listSubs, 0, wx.ALL|wx.EXPAND)
        sizerLists.Add(self.listEspms, 0, wx.ALL|wx.EXPAND)
        sizerLists.AddGrowableRow(1)
        sizerLists.AddGrowableCol(0)
        sizerLists.AddGrowableCol(1)
        sizerMain.Add(sizerLists, 1, wx.EXPAND)

        sizerNotes = wx.FlexGridSizer(2, 1, 5, 0)
        sizerNotes.Add(wx.StaticText(self, -1, _('Notes:')))
        sizerNotes.Add(wx.TextCtrl(self, -1, ''.join(notes), style=wx.TE_READONLY|wx.TE_MULTILINE), 1, wx.EXPAND)
        sizerNotes.AddGrowableCol(0)
        sizerNotes.AddGrowableRow(1)
        sizerMain.Add(sizerNotes, 2, wx.TOP|wx.EXPAND)

        sizerChecks = wx.FlexGridSizer(1, 2, 5, 0)
        self.checkApply = wx.CheckBox(self, 111, _("Apply these selections"))
        self.checkApply.SetValue(bAuto)
        wx.EVT_CHECKBOX(self, 111, self.OnCheckApply)
        sizerChecks.AddStretchSpacer()
        sizerChecks.Add(self.checkApply)
        sizerChecks.AddGrowableRow(0)
        sizerChecks.AddGrowableCol(0)
        sizerMain.Add(sizerChecks, 3, wx.EXPAND|wx.TOP)

        self.parent.FindWindowById(wx.ID_FORWARD).Enable(bAuto)
        self.parent.finishing = True

        sizerMain.AddGrowableCol(0)
        sizerMain.AddGrowableRow(1)
        sizerMain.AddGrowableRow(2)
        self.SetSizer(sizerMain)
        self.Layout()

    def OnCheckApply(self, event):
        self.parent.FindWindowById(wx.ID_FORWARD).Enable(self.checkApply.IsChecked())

    def GetNext(self): return None

    # Undo selecting/deselection of items for UI consistency
    def OnSelectSubs(self, event):
        index = event.GetSelection()
        self.listSubs.Check(index, not self.listSubs.IsChecked(index))
    def OnSelectEspms(self, event):
        index = event.GetSelection()
        self.listEspms.Check(index, not self.listEspms.IsChecked(index))
    
# End PageFinish -------------------------------------


# PageVersions ---------------------------------------
#  Page for displaying what versions an installer
#  requires/recommends and what you have installed
#  for Fallout, FOSE, and FOGE, and Wrye Bash
#-----------------------------------------------------
class PageVersions(PageInstaller):
    def __init__(self, parent, bFoOk, foHave, foNeed, bFOSEOk, foseHave, foseNeed, bFOGEOk, fogeHave, fogeNeed, bWBOk, wbHave, wbNeed):
        PageInstaller.__init__(self, parent)

        bmp = [wx.Bitmap(bosh.dirs['mopy'].join('images', 'x.png').s),
               wx.Bitmap(bosh.dirs['mopy'].join('images', 'check.png').s)
               ] 

        sizerMain = wx.FlexGridSizer(5, 1, 0, 0)

        self.textWarning = wx.StaticText(self, 124, _('WARNING: The following version requirements are not met for using this installer.'))
        self.textWarning.Wrap(gDialogSize[0]-20)
        sizerMain.Add(self.textWarning, 0, wx.ALL|wx.ALIGN_CENTER, 5)

        sizerVersionsTop = wx.StaticBoxSizer(wx.StaticBox(self, -1, _('Version Requirements')))
        sizerVersions = wx.FlexGridSizer(5, 4, 5, 5)
        sizerVersionsTop.Add(sizerVersions, 1, wx.EXPAND, 0)

        sizerVersions.AddStretchSpacer()
        sizerVersions.Add(wx.StaticText(self, -1, _('Need')))
        sizerVersions.Add(wx.StaticText(self, -1, _('Have')))
        sizerVersions.AddStretchSpacer()

        linkFo = wx.HyperlinkCtrl(self, -1, 'Fallout', 'http://fallout.bethsoft.com/eng/downloads/updates.html')
        linkFo.SetVisitedColour(linkFo.GetNormalColour())
        linkFo.SetToolTip(wx.ToolTip('http://fallout.bethsoft.com/'))
        sizerVersions.Add(linkFo)
        sizerVersions.Add(wx.StaticText(self, -1, foNeed))
        sizerVersions.Add(wx.StaticText(self, -1, foHave))
        sizerVersions.Add(wx.StaticBitmap(self, -1, bmp[bFoOk]))

        linkFOSE = wx.HyperlinkCtrl(self, -1, 'Fallout Script Extender', 'http://fose.silverlock.org/')
        linkFOSE.SetVisitedColour(linkFOSE.GetNormalColour())
        linkFOSE.SetToolTip(wx.ToolTip('http://fose.silverlock.org/'))
        sizerVersions.Add(linkFOSE)
        sizerVersions.Add(wx.StaticText(self, -1, foseNeed))
        sizerVersions.Add(wx.StaticText(self, -1, foseHave))
        sizerVersions.Add(wx.StaticBitmap(self, -1, bmp[bFOSEOk]))

        # linkFOGE = wx.HyperlinkCtrl(self, -1, 'Fallout Graphics Extender', 'http://timeslip.chorrol.com/foge.html')
        # linkFOGE.SetVisitedColour(linkFOGE.GetNormalColour())
        # linkFOGE.SetToolTip(wx.ToolTip('http://timeslip.chorrol.com/'))
        # sizerVersions.Add(linkFOGE)
        # sizerVersions.Add(wx.StaticText(self, -1, fogeNeed))
        # sizerVersions.Add(wx.StaticText(self, -1, fogeHave))
        # sizerVersions.Add(wx.StaticBitmap(self, -1, bmp[bFOGEOk]))

        linkWB = wx.HyperlinkCtrl(self, -1, 'Wrye Flash', 'http://fallout3nexus.com/downloads/file.php?id=11336')
        linkWB.SetVisitedColour(linkWB.GetNormalColour())
        linkWB.SetToolTip(wx.ToolTip('http://fallout3nexus.com/'))
        sizerVersions.Add(linkWB)
        sizerVersions.Add(wx.StaticText(self, -1, wbNeed))
        sizerVersions.Add(wx.StaticText(self, -1, wbHave))
        sizerVersions.Add(wx.StaticBitmap(self, -1, bmp[bWBOk]))

        sizerVersions.AddGrowableCol(0)
        sizerVersions.AddGrowableCol(1)
        sizerVersions.AddGrowableCol(2)
        sizerVersions.AddGrowableCol(3)
        sizerMain.Add(sizerVersionsTop, 2, wx.ALL|wx.EXPAND, 5)
        
        sizerMain.AddStretchSpacer()
        
        sizerCheck = wx.FlexGridSizer(1, 2, 5, 5)
        self.checkOk = wx.CheckBox(self, 123, _('Install anyway.'))
        wx.EVT_CHECKBOX(self, 123, self.OnCheck)
        self.parent.FindWindowById(wx.ID_FORWARD).Enable(False)
        sizerCheck.AddStretchSpacer()
        sizerCheck.Add(self.checkOk)
        sizerCheck.AddGrowableRow(0)
        sizerCheck.AddGrowableCol(0)
        sizerMain.Add(sizerCheck, 3, wx.EXPAND)

        self.SetSizer(sizerMain)
        sizerMain.AddGrowableRow(0)
        sizerMain.AddGrowableRow(2)
        sizerMain.AddGrowableCol(0)
        self.Layout()

    def OnCheck(self, event):
        self.parent.FindWindowById(wx.ID_FORWARD).Enable(self.checkOk.IsChecked())
# END PageVersions -----------------------------------------------

# WryeParser -----------------------------------------------------
#  a derived class of Parser, for handling BAIN install
#  wizards
#-----------------------------------------------------------------                        
class WryeParser(ScriptParser.Parser):
    def __init__(self, parent, installer, subs, bArchive, path, bAuto):
        ScriptParser.Parser.__init__(self)
        
        self.parent = parent
        self.installer = installer
        self.bArchive = bArchive
        self.path = path
        self.bAuto = bAuto
        self.notes = []
        self.page = None

        self.sublist = {}
        self.espmlist = {}
        for i in installer.espmMap.keys():
            for j in installer.espmMap[i]:
                if j not in self.espmlist:
                    self.espmlist[j] = False
            if i == '': continue
            self.sublist[i] = False

        #--Operators
        #Assignment
        self.SetOperator('=' , self.Ass, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        self.SetOperator('+=', self.AssAdd, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        self.SetOperator('-=', self.AssMin, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        self.SetOperator('*=', self.AssMul, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        self.SetOperator('/=', self.AssDiv, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        #self.SetOperator('%=', self.AssMod, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        self.SetOperator('^=', self.AssExp, ScriptParser.OP.ASS, ScriptParser.RIGHT)
        #Comparison
        self.SetOperator('==', self.opE, ScriptParser.OP.CO2)
        self.SetOperator('!=', self.opNE, ScriptParser.OP.CO2)
        self.SetOperator('>=', self.opGE, ScriptParser.OP.CO1)
        self.SetOperator('>' , self.opG, ScriptParser.OP.CO1)
        self.SetOperator('<=', self.opLE, ScriptParser.OP.CO1)
        self.SetOperator('<' , self.opL, ScriptParser.OP.CO1)
        #Membership operators
        self.SetOperator('in', self.opIn, ScriptParser.OP.MEM, passTokens=False)
        #Boolean
        self.SetOperator('&' , self.opAnd, ScriptParser.OP.AND)
        self.SetOperator('and', self.opAnd, ScriptParser.OP.AND)
        self.SetOperator('|', self.opOr, ScriptParser.OP.OR)
        self.SetOperator('or', self.opOr, ScriptParser.OP.OR)
        self.SetOperator('!', self.opNot, ScriptParser.OP.NOT, ScriptParser.RIGHT)
        self.SetOperator('not', self.opNot, ScriptParser.OP.NOT, ScriptParser.RIGHT)
        #Post-fix increment/decrement
        self.SetOperator('++', self.opInc, ScriptParser.OP.UNA)
        self.SetOperator('--', self.opDec, ScriptParser.OP.UNA)
        #Math
        self.SetOperator('+', self.opAdd, ScriptParser.OP.ADD)
        self.SetOperator('-', self.opMin, ScriptParser.OP.ADD)
        self.SetOperator('*', self.opMul, ScriptParser.OP.MUL)
        self.SetOperator('/', self.opDiv, ScriptParser.OP.MUL)
        #self.SetOperator('%', self.opMod, ScriptParser.OP.MUL)
        self.SetOperator('^', self.opExp, ScriptParser.OP.EXP, ScriptParser.RIGHT)

        #--Functions
        self.SetFunction('CompareFalloutVersion', self.fnCompareFalloutVersion, 1)
        self.SetFunction('CompareFOSEVersion', self.fnCompareFOSEVersion, 1)
        self.SetFunction('CompareFOGEVersion', self.fnCompareFOGEVersion, 1)
        self.SetFunction('CompareWBVersion', self.fnCompareWBVersion, 1)
        self.SetFunction('DataFileExists', self.fnDataFileExists, 1)
        self.SetFunction('str', self.fnStr, 1)
        self.SetFunction('int', self.fnInt, 1)
        self.SetFunction('float', self.fnFloat, 1)
        self.SetFunction('len', self.fnLen, 1)
        #--Keywords
        self.SetKeyword('SelectSubPackage', self.kwdSelectSubPackage, 1)
        self.SetKeyword('DeSelectSubPackage', self.kwdDeSelectSubPackage, 1)
        self.SetKeyword('SelectEspm', self.kwdSelectEspm, 1)
        self.SetKeyword('DeSelectEspm', self.kwdDeSelectEspm, 1)
        self.SetKeyword('SelectAll', self.kwdSelectAll)
        self.SetKeyword('DeSelectAll', self.kwdDeSelectAll)
        self.SetKeyword('SelectAllEspms', self.kwdSelectAllEspms)
        self.SetKeyword('DeSelectAllEspms', self.kwdDeSelectAllEspms)
        self.SetKeyword('Note', self.kwdNote, 1, ScriptParser.KEY.NO_MAX, True, True)
        self.SetKeyword('If', self.kwdIf, 1, ScriptParser.KEY.NO_MAX, True, True)
        self.SetKeyword('Elif', self.kwdElif, 1, ScriptParser.KEY.NO_MAX, True, True)
        self.SetKeyword('Else', self.kwdElse)
        self.SetKeyword('EndIf', self.kwdEndIf)
        self.SetKeyword('SelectOne', self.kwdSelectOne, 7, ScriptParser.KEY.NO_MAX)
        self.SetKeyword('SelectMany', self.kwdSelectMany, 4, ScriptParser.KEY.NO_MAX)
        self.SetKeyword('Case', self.kwdCase, 1, ScriptParser.KEY.NO_MAX)
        self.SetKeyword('Default', self.kwdDefault)
        self.SetKeyword('Break', self.kwdBreak)
        self.SetKeyword('EndSelect', self.kwdEndSelect)
        self.SetKeyword('Return', self.kwdReturn)
        self.SetKeyword('Cancel', self.kwdCancel, 0, ScriptParser.KEY.NO_MAX)
        self.SetKeyword('RequireVersions', self.kwdRequireVersions, 1, 4)


    def Begin(self, file):
        self.vars = {}
        self.Flow = []

        if file.exists() and file.isfile():
            script = file.open()
            self.lines = script.readlines()
            script.close()
            return self.Continue()
        balt.showWarning(self.parent, _('Could not open wizard file'))
        return None

    def Continue(self):
        self.page = None
        while len(self.lines) > 0:
            newline = self.lines.pop(0)
            try:
                self.RunLine(newline)
            except ScriptParser.ParserError, e:
                return PageError(self.parent, _('Installer Wizard'), _('An error occured in the wizard script:\n Line:\t%s\n Error:\t%s') % (newline.strip('\n'), e))
            except Exception, e:
                return PageError(self.parent, _('Installer Wizard'), _('An unhandled error occured while parsing the wizard:\n Line:\t%s\n Error:\t%s') % (newline.strip('\n'), e))
            if self.page:
                return self.page
        return PageFinish(self.parent, self.sublist, self.espmlist, self.bAuto, self.notes)

    def EspmIsInPackage(self, esmp, package):
        package = package.lower()
        espm = espm.lower()
        for i in self.installer.espmMap:
            if package == i.lower():
                for j in self.installer.espmMap[i]:
                    if espm == j.lower():
                        return True
        return False
    def EspmList(self, package):
        pack = self.GetPackage(package)
        if pack in self.installer.espmMap:
            return self.installer.espmMap[pack]
        return []
    def PackageList(self, espm):
        ret = []
        for i in self.sublist:
            if self.EspmIsInPackage(espm, i):
                ret.append(i)
        return ret
    def EspmHasActivePackage(self, esmp):
        for i in self.sublist:
            if self.EspmIsInPackage(espm, i):
                if self.sublist[i]:
                    return True
        return False
    def GetPackage(self, package):
        package = package.lower()
        for i in self.sublist:
            if package == i.lower():
                return i
        return None
    def GetEspm(self, espm):
        espm = espm.lower()
        for i in self.espmlist:
            if espm == i.lower():
                return i
        return None

    # Assignment operators
    def Ass(self, l, r):
        if l.type not in [ScriptParser.VARIABLE,ScriptParser.NAME]:
            self.error('Cannot assign a value to %s, type is %s.' % (l.text, ScriptParser.Types[l.type]))
        self.variables[l.text] = r.data
        return r.data
    def AssAdd(self, l, r): return self.Ass(l, l+r)
    def AssMin(self, l, r): return self.Ass(l, l-r)
    def AssMul(self, l, r): return self.Ass(l, l*r)
    def AssDiv(self, l, r): return self.Ass(l, l/r)
    def AssMod(self, l, r): return self.Ass(l, l%r)
    def AssExp(self, l, r): return self.Ass(l, l**r)
    # Comparison operators
    def opE(self, l, r): return l == r
    def opNE(self, l, r): return l != r
    def opGE(self, l, r): return l >= r
    def opG(self, l, r): return l > r
    def opLE(self, l, r): return l <= r
    def opL(self, l, r): return l < r
    # Membership tests
    def opIn(self, l, r): return l in r
    # Boolean operators
    def opAnd(self, l, r): return l and r
    def opOr(self, l, r): return l or r
    def opNot(self, l): return not l
    # Postfix inc/dec
    def opInc(self, l):
        l += 1
        return l
    def opDec(self, l):
        l -= 1
        return l
    # Math operators
    def opAdd(self, l, r): return l + r
    def opMin(self, l, r): return l - r
    def opMul(self, l, r): return l * r
    def opDiv(self, l, r): return l / r
    def opMod(self, l, r): return l % r
    def opExp(self, l, r): return l ** r

    # Functions...
    def fnCompareFalloutVersion(self, foWant):
        ret = self._TestVersion(self._TestVersion_Want(foWant), bosh.dirs['app'].join('fallout3.exe'))
        return ret[0]
    def fnCompareFOSEVersion(self, foseWant):
        ret = self._TestVersion(self._TestVersion_Want(foseWant), bosh.dirs['app'].join('fose_loader.exe'))
        return ret[0]
    def fnCompareFOGEVersion(self, fogeWant):
        ret = self._TestVersion_FOGE(self._TestVersion_Want(fogeWant))
        return ret[0]
    def fnCompareWBVersion(self, wbWant):
        wbHave = bosh.settings['bash.readme'][1]
        return cmp(float(wbHave), float(wbWant))
    def fnDataFileExists(self, filename):
        return bosh.dirs['mods'].join(filename).exists()
    def fnStr(self, data): return str(data)
    def fnInt(self, data):
        try:
            return int(data)
        except:
            return 0
    def fnFloat(self, data):
        try:
            return float(data)
        except:
            return 0.0
    def fnLen(self, data):
        try:
            return len(data)
        except:
            return 0

    # Keywords, mostly for flow control (If, Select, etc)
    def kwdIf(self, *args):
        if self.LenFlow() > 0 and self.PeekFlow().type == 'If' and not self.PeekFlow().active:
            #Inactive portion of an If-Elif-Else-EndIf statement, but we hit an If, so we need
            #To not count the next 'EndIf' towards THIS one
            self.PushFlow('If', False, ['If', 'EndIf'])
            return
        bActive = self.ExecuteTokens(args)
        self.PushFlow('If', bActive, ['If', 'Else', 'Elif', 'EndIf'], ifTrue=bActive, hitElse=False)
    def kwdElif(self, *args):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'If' or self.PeekFlow().hitElse:
            self.error(UNEXPECTED % 'Elif')
        if self.PeekFlow().ifTrue:
            self.PeekFlow().active = False
        else:
            self.PeekFlow().active = self.ExecuteTokens(args)
            self.PeekFlow().ifTrue = self.PeekFlow().active or self.PeekFlow().ifTrue
    def kwdElse(self):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'If' or self.PeekFlow().hitElse:
            self.error(UNEXPECTED % 'Else')
        if self.PeekFlow().ifTrue:
            self.PeekFlow().active = False
            self.PeekFlow().hitElse = True
        else:
            self.PeekFlow().active = True
            self.PeekFlow().hitElse = True
    def kwdEndIf(self):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'If':
            self.error(UNEXPECTED % 'EndIf')
        self.PopFlow()

    def kwdSelectOne(self, *args): self._KeywordSelect(False, 'SelectOne', *args)
    def kwdSelectMany(self, *args): self._KeywordSelect(True, 'SelectMany', *args)
    def _KeywordSelect(self, bMany, name, *args):
        args = list(args)
        if self.LenFlow() > 0 and self.PeekFlow().type == 'Select' and not self.PeekFlow().active:
            #We're inside an invalid Case for a Select alread, so just add a blank FlowControl for
            #this select
            self.PushFlow('Select', False, ['SelectOne', 'SelectMany', 'EndSelect'])
            return
        main_desc = args.pop(0)
        if len(args) % 3:
            self.error(MISSING_ARGS % name)
        images = []
        titles = []
        descs = []
        defaultMap = []
        image_paths = []
        while len(args):
            title = args.pop(0)
            if title[0] == '|':
                defaultMap.append(True)
                titles.append(title[1:])
            else:
                defaultMap.append(False)
                titles.append(title)
            descs.append(args.pop(0))
            images.append(args.pop(0))
        if self.bAuto:
            temp = []
            for index in range(len(titles)):
                if defaultMap[index]:
                    temp.append(titles[index])
                    if not bMany:
                        break
            self.PushFlow('Select', False, ['SelectOne', 'SelectMany', 'Case', 'Default', 'EndSelect'], values=temp, hitCase=False)
            return
        if self.bArchive:
            temp = []
            for i in images:
                if i == '': continue
                temp.append(i)
            if len(temp):
                self.installer.unpackToTemp(self.path, temp)
            for i in images:
                image_paths.append(self.installer.tempDir.join(i))
        else:
            for i in images:
                image_paths.append(bosh.dirs['installers'].join(self.path.s, i))
        self.page = PageSelect(self.parent, bMany, _('Installer Wizard'), main_desc, titles, descs, image_paths, defaultMap)
    def kwdCase(self, *args):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'Select':
            self.error(UNEXPECTED % 'Case')
        case = ' '.join(args)
        self.PeekFlow().hitCase = True
        if case in self.PeekFlow().values:
            self.PeekFlow().active = True
    def kwdDefault(self):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'Select':
            self.error(UNEXPECTED % 'Default')
        if self.PeekFlow().hitCase:
            return
        self.PeekFlow().active = True
        self.PeekFlow().hitCase = True
    def kwdBreak(self):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'Select':
            self.error(UNEXPECTED % 'Break')
        self.PeekFlow().active = False
    def kwdEndSelect(self):
        if self.LenFlow() == 0 or self.PeekFlow().type != 'Select':
            self.error(UNEXPECTED % 'EndSelect')
        self.PopFlow()

    # Package selection functions
    def kwdSelectSubPackage(self, subpackage): self._SelectSubPackage(True, subpackage)
    def kwdDeSelectSubPackage(self, subpackage): self._SelectSubPackage(False, subpackage)
    def _SelectSubPackage(self, bSelect, subpackage):
        package = self.GetPackage(subpackage)
        if package:
            self.sublist[package] = bSelect
            for i in self.EspmList(package):
                if bSelect:
                    self._SelectEspm(True, i)
                else:
                    if not self.EspmHasActivePackage(i):
                        self._SelectEspm(False, i)
        else:
            self.error(_("Sub-package '%s' is not a part of the installer.") % subpackage)
    def kwdSelectAll(self): self._SelectAll(True)
    def kwdDeSelectAll(self): self._SelectAll(False)
    def _SelectAll(self, bSelect):
        for i in self.sublist.keys():
            self.sublist[i] = bSelect
        for i in self.espmlist.keys():
            self.espmlist[i] = bSelect
    def kwdSelectEspm(self, espm): self._SelectEspm(True, espm)
    def kwdDeSelectEspm(self, espm): self._SelectEspm(False, espm)
    def _SelectEspm(self, bSelect, name):
        espm = self.GetEspm(name)
        if espm:
            self.espmlist[espm] = bSelect
        else:
            self.error(_("Espm '%s' is not a part of the installer.") % name)
    def kwdSelectAllEspms(self): self._SelectAllEspms(True)
    def kwdDeSelectAllEspms(self): self._SelectAllEspms(False)
    def _SelectAllEspms(self, bSelect):
        for i in self.espmlist.keys():
            self.espmlist[i] = bSelect

    def kwdNote(self, *args):
        temp = []
        for i in args:
            if i.type in [ScriptParser.CONSTANT,
                          ScriptParser.VARIABLE,
                          ScriptParser.NAME,
                          ScriptParser.STRING,
                          ScriptParser.INTEGER,
                          ScriptParser.DECIMAL]:
                temp.append(str(i.data))
            else:
                temp.append(str(i.text))
        self.notes.append('- %s\n' % ' '.join(temp))
    def kwdRequireVersions(self, fo, fose='None', foge='None', wbWant=0):
        if self.bAuto: return
        
        foWant = self._TestVersion_Want(fo)
        if foWant == 'None': fo = 'None'
        foseWant = self._TestVersion_Want(fose)
        if foseWant == 'None': fose = 'None'
        fogeWant = self._TestVersion_Want(foge)
        if fogeWant == 'None': foge = 'None'
        wbHave = bosh.settings['bash.readme'][1]

        ret = self._TestVersion(foWant, bosh.dirs['app'].join('fallout3.exe'))
        bFoOk = ret[0] >= 0
        foHave = ret[1]
        ret = self._TestVersion(foseWant, bosh.dirs['app'].join('fose_loader.exe'))
        bFOSEOk = ret[0] >= 0
        foseHave = ret[1]
        ret = self._TestVersion_FOGE(fogeWant)
        bFOGEOk = ret[0] >= 0
        fogeHave = ret[1]
        bWBOk = float(wbHave) >= float(wbWant)

        if not bFoOk or not bFOSEOk or not bFOGEOk:
            self.page = PageVersions(self.parent, bFoOk, foHave, fo, bFOSEOk, foseHave, fose, bFOGEOk, fogeHave, foge, bWBOk, wbHave, wbWant)
    def _TestVersion_FOGE(self, want):
        retFOGEOld = self._TestVersion(want, bosh.dirs['mods'].join('fose', 'plugins', 'foge.dll'))
        retFOGENew = self._TestVersion(want, bosh.dirs['mods'].join('fose', 'plugins', 'fogev2.dll'))
        haveNew = retFOGENew[1]
        haveOld = retFOGEOld[1]
        if haveNew != 'None':
            # FOGEv2 is installed, use that for comparison
            return retFOGENew
        else:
            # FOGEv2 isn't installed
            return retFOGEOld
    def _TestVersion_Want(self, want):
        try:
            need = [int(i) for i in want.split('.')]
        except:
            need = 'None'
        return need
    def _TestVersion(self, need, file):
        if file.exists():
            info = win32api.GetFileVersionInfo(file.s, '\\')
            ms = info['FileVersionMS']
            ls = info['FileVersionLS']
            have = win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls)
            ver = '.'.join([str(i) for i in have])
            if need == 'None':
                return [1, ver]
            if len(need) != 4:
                self.error(_("Version '%s' expected in format 'x.x.x.x'") % want)
                return [-1, ver]
            if have[0] > need[0]: return [1, ver]
            if have[0] < need[0]: return [-1, ver]
            if have[1] > need[1]: return [1, ver]
            if have[1] < need[1]: return [-1, ver]
            if have[2] > need[2]: return [1, ver]
            if have[2] < need[2]: return [-1, ver]
            if have[3] > need[3]: return [1, ver]
            if have[3] < need[3]: return [-1, ver]
            return [0, ver]
        elif need == 'None':
            return [0, 'None']
        return [-1, 'None']
    def kwdReturn(self):
        self.page = PageFinish(self.parent, self.sublist, self.espmlist, self.bAuto, self.notes)
    def kwdCancel(self, *args):
        if len(args) < 1:
            msg = _("No reason given")
        else:
            msg = ' '.join(args)
        self.page = PageError(self.parent, _('The installer wizard was canceled:'), msg)
# END --------------------------------------------------------------------------------------------------
