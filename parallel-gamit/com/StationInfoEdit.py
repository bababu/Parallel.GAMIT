"""
Project:
Date: 10/10/17 3:07 PM
Author: Demian D. Gomez
"""

import argparse
import curses
import curses.ascii
import traceback
from collections import OrderedDict
from curses import panel
from curses.textpad import Textbox, rectangle

import dbConnection
import pyDate
import pyOptions
import pyStationInfo

cnn = dbConnection.Cnn('gnss_data.cfg')
Config = pyOptions.ReadOptions("gnss_data.cfg")  # type: pyOptions.ReadOptions
selection = 0
stn = None
records = []


class _Textbox(Textbox):
    """
    curses.textpad.Textbox requires users to ^g on completion, which is sort
    of annoying for an interactive chat client such as this, which typically only
    reuquires an enter. This subclass fixes this problem by signalling completion
    on Enter as well as ^g. Also, map <Backspace> key to ^h.
    """

    def __init__(self, win, insert_mode=False, text=''):
        Textbox.__init__(self, win, insert_mode)

        for chr in text:
            if chr == '\n':
                Textbox.do_command(self, curses.ascii.NL)
            else:
                Textbox.do_command(self, chr)

    def edit(self, validate=None):
        """
        Edit in the widget window and collect the results.
        """
        while 1:
            ch = self.win.getch()
            if validate:
                ch = validate(ch)
            if not ch:
                continue
            r = self.do_command(ch)
            if not r or r == -1:
                break
            self.win.refresh()

        if r != -1:
            return self.gather()
        else:
            return None

    def do_command(self, ch):
        if ch == 127:  # backspace
            Textbox.do_command(self,curses.KEY_BACKSPACE)
            self.win.refresh()
            return 1
        if ch == 27:
            Textbox.gather(self)
            return -1
        return Textbox.do_command(self, ch)


class Menu(object):

    def __init__(self, cnn, items, stdscreen, title='', type='main', record_index=None):
        self.window = stdscreen.subwin(0,0)
        self.window.keypad(1)
        self.panel = panel.new_panel(self.window)
        self.panel.hide()
        panel.update_panels()

        self.position = 0
        self.items = items
        if type == 'edit':
            self.items.append({'field': 'Save and exit', 'function': 'save_changes'})
        else:
            self.items.append({'field': 'Exit', 'function': 'exit'})

        self.title = title
        self.type = type
        self.edited_fields = dict()
        self.record_index = record_index
        self.cnn = cnn

    def navigate(self, n):
        self.position += n
        if self.position < 0:
            self.position = 0
        elif self.position >= len(self.items):
            self.position = len(self.items)-1

    def display(self):
        self.panel.top()
        self.panel.show()
        self.window.clear()

        while True:
            self.window.refresh()

            if self.title:
                sx = 2
                self.window.addstr(1, 1, self.title, curses.color_pair(1))
            else:
                sx = 1

            curses.doupdate()
            for index, item in enumerate(self.items):
                if index == self.position:
                    mode = curses.A_REVERSE
                else:
                    mode = curses.A_NORMAL

                if self.type == 'edit' and index < len(self.items)-1:
                    msg = '%2d. %20s: %-30s' % (index, item['field'],
                                                item['value'].replace('\n', ' ')
                                                if len(item['value']) <= 30
                                                else item['value'].replace('\n', ' ')[0:25] + '...')
                    self.window.addstr(sx + index, 1, msg, mode)
                else:
                    msg = '%2d. %s' % (index, item['field'])
                    self.window.addstr(sx+index, 1, msg, mode)

            key = self.window.getch()

            if key in [curses.KEY_ENTER, ord('\n')]:
                if self.position == len(self.items) - 1 and self.type != 'edit':
                    break

                elif self.position < len(self.items) - 1 and self.type != 'edit':
                    self.items[self.position]['function'](self)

                else:
                    if self.position == len(self.items) - 1:
                        # save changes
                        if save_changes(self):
                            break
                    else:
                        # enter edit mode
                        self.enter_edit_mode()

            elif key == curses.KEY_UP:
                self.navigate(-1)

            elif key == curses.KEY_DOWN:
                self.navigate(1)

            elif key == 27: # escape (cancel)
                break
            else:
                if self.type == 'edit':
                    # edit mode, hightlight the field and replace text
                    if key == 4: # control + D
                        # ask if user want to delete record
                        self.window.addstr(sx + len(self.items), 1,
                                           'Are you sure you want to delete this record?', curses.color_pair(2))
                        key = self.window.getch()
                        if chr(key).upper() == 'Y':
                            # delete record
                            delete_record(self)
                            break
                    else:
                        if key < 256:
                            self.enter_edit_mode(chr(key))

                    self.window.clear()

        self.window.clear()
        self.panel.hide()
        panel.update_panels()
        curses.doupdate()

    def enter_edit_mode(self, value=None):

        if self.items[self.position]['field'] == 'Comments':
            editwin = curses.newwin(10, 60, self.position+2, 27)
            rectangle(self.window, self.position + 1, 26, self.position + 12, 26 + 61)
        else:
            editwin = curses.newwin(1, 30, self.position+2, 27)

        editwin.attron(curses.color_pair(2))
        curses.curs_set(1)
        if value:
            box = _Textbox(editwin, True, text=value)
        else:
            box = _Textbox(editwin, True, text=self.items[self.position]['value'])

        _Textbox.stripspaces = True

        self.window.refresh()

        while True:
            edit_field = box.edit()
            if not edit_field is None:
                result = self.validate(edit_field.strip())
                if result:
                    self.navigate(1)
                    break
            else:
                break

        curses.curs_set(0)

        self.window.clear()

    def validate(self, edit_field):

        if self.items[self.position]['field'] in ['DateStart', 'DateEnd']:
            # VALIDATE THE date strings
            try:
                if edit_field.strip() == '' and self.items[self.position]['field'] == 'DateEnd':
                    edit_field = str(pyDate.Date(stninfo=None))
                else:
                    # if success, then reformat the datetime
                    edit_field = str(pyDate.Date(stninfo=edit_field))

            except Exception:
                self.ShowError('Invalid station information datetime format!')
                return False

        elif self.items[self.position]['field'] == 'AntennaCode':
            rs = self.cnn.query('SELECT * FROM antennas WHERE "AntennaCode" = \'%s\'' % (edit_field.upper()))

            if rs.ntuples() == 0:
                self.ShowError('Antenna code could not be found!')
                return False
            else:
                edit_field = rs.dictresult()[0]['AntennaCode']

        elif self.items[self.position]['field'] == 'ReceiverCode':
            rs = self.cnn.query('SELECT * FROM receivers WHERE "ReceiverCode" = \'%s\'' % (edit_field.upper()))

            if rs.ntuples() == 0:
                self.ShowError('Receiver code could not be found!')
                return False
            else:
                edit_field = rs.dictresult()[0]['ReceiverCode']

        elif self.items[self.position]['field'] in ['AntennaEast', 'AntennaNorth', 'AntennaHeight']:
            # field has to be numeric
            try:
                _ = float(edit_field)

            except Exception:
                self.ShowError('Value must be numeric!')
                return False

        elif self.items[self.position]['field'] == 'HeightCode':

            if not edit_field.upper() in ['DHTGP', 'DHPAB', 'SLBDN', 'SLBCR', 'SLTEP', 'DHBCR', 'SLHGP',
                                          'SLTGN', 'DHARP', 'SLBCE']:
                self.ShowError('Value must be one of the following: ' + ' '.join(['DHTGP', 'DHPAB', 'SLBDN', 'SLBCR',
                                                                                  'SLTEP', 'DHBCR', 'SLHGP', 'SLTGN',
                                                                                  'DHARP', 'SLBCE']))
                return False
            else:
                edit_field = edit_field.upper()
        else:
            edit_field = edit_field.upper()

        self.edited_fields[self.items[self.position]['field']] = edit_field
        self.items[self.position]['value'] = edit_field
        return True

    def ShowError(self, error):
        self.window.addstr(self.position + 2, 60, ' -> ' + error, curses.color_pair(2))
        self.window.refresh()


def delete_record(menu):
    global StnInfo

    if not 'New station information' in menu.title:
        StnInfo.DeleteStationInfo(StnInfo.records[menu.record_index])


def save_changes(menu):
    # trigger an update of the station info
    global StnInfo

    # check if there are any changes
    if len(list(menu.edited_fields.keys())) > 0:

        record = dict()
        record['NetworkCode'] = stn['NetworkCode']
        record['StationCode'] = stn['StationCode']

        for item in menu.items[0:-1]:
            if item['field'] in list(menu.edited_fields.keys()):
                record[item['field']] = menu.edited_fields[item['field']]
            else:
                record[item['field']] = item['value']

            if item['field'] in ['DateStart', 'DateEnd']:

                if item['field'] == 'DateEnd' and item['value'].strip() == '':
                    record[item['field']] = None

        # convert the dictionary into a valid StationInfoRecord object
        record = pyStationInfo.StationInfoRecord(stn['NetworkCode'], stn['StationCode'], record)

        # try to insert and catch errors
        try:
            if 'New station information' in menu.title:
                # insert new
                StnInfo.InsertStationInfo(record)
            else:
                # update a station info record
                StnInfo.UpdateStationInfo(StnInfo.records[menu.record_index], record)

        except Exception as e:
            menu.ShowError(traceback.format_exc())
            return False

        # nothing failed, exit
    return True


def get_records():

    global StnInfo
    StnInfo = pyStationInfo.StationInfo(cnn, stn['NetworkCode'], stn['StationCode'], allow_empty=True)

    out = []

    if StnInfo.record_count > 0:
        records = StnInfo.return_stninfo_short().split('\n')

        for record in records:
            out.append({'field': record, 'function': selection_main_menu})

    return out


def selection_main_menu(menu):
    global StnInfo

    if menu.position < StnInfo.record_count:
        # edit
        edit_record(menu.position)

    elif menu.position == StnInfo.record_count:

        if len(StnInfo.records) > 0:
            stninfo = StnInfo.records[-1]
        else:
            stninfo = None

        # insert new record
        record = OrderedDict()

        record['DateStart'] = ''
        record['DateEnd'] = ''
        record['AntennaHeight'] = '0.000' if stninfo is None else stninfo['AntennaHeight']
        record['HeightCode'] = 'DHARP' if stninfo is None else stninfo['HeightCode']
        record['AntennaNorth'] = '0.000' if stninfo is None else stninfo['AntennaNorth']
        record['AntennaEast'] = '0.000' if stninfo is None else stninfo['AntennaEast']
        record['ReceiverCode'] = '' if stninfo is None else stninfo['ReceiverCode']
        record['ReceiverVers'] = '' if stninfo is None else stninfo['ReceiverVers']
        record['ReceiverFirmware'] = '' if stninfo is None else stninfo['ReceiverFirmware']
        record['ReceiverSerial'] = '' if stninfo is None else stninfo['ReceiverSerial']
        record['AntennaCode'] = '' if stninfo is None else stninfo['AntennaCode']
        record['RadomeCode'] = '' if stninfo is None else stninfo['RadomeCode']
        record['AntennaSerial'] = '' if stninfo is None else stninfo['AntennaSerial']
        record['Comments'] = ''

        new_record = []

        for field, value in record.items():
            new_record.append({'field': field, 'value': str(value)})

        # new_record = sorted(new_record, key=lambda k: k['field'])

        edit_menu = Menu(cnn, new_record, screen, 'New station information record (ESC to cancel)', 'edit')

        edit_menu.display()

    elif menu.position == StnInfo.record_count+1:
        exit()

    # reload the main menu
    menu.items = get_records()
    menu.items += [{'field': 'Insert new station information record', 'function': selection_main_menu}]
    menu.items += [{'field': 'Exit', 'function': 'exit'}]

    return


def edit_record(position):

    global StnInfo

    items = get_fields(position)

    menu = Menu(cnn, items, screen, 'Editing (ESC to cancel): ' +
                StnInfo.return_stninfo_short().split('\n')[position], 'edit', record_index=position)

    menu.display()


def get_fields(position):
    out = []
    global StnInfo

    record = StnInfo.records[position]

    # specific order as requested Eric
    record2 = OrderedDict()

    record2['DateStart'] = ''
    record2['DateEnd'] = ''
    record2['AntennaHeight'] = '0.000'
    record2['HeightCode'] = 'DHARP'
    record2['AntennaNorth'] = '0.000'
    record2['AntennaEast'] = '0.000'
    record2['ReceiverCode'] = ''
    record2['ReceiverVers'] = ''
    record2['ReceiverFirmware'] = ''
    record2['ReceiverSerial'] = ''
    record2['AntennaCode'] = ''
    record2['RadomeCode'] = ''
    record2['AntennaSerial'] = ''
    record2['Comments'] = ''

    for key in list(record2.keys()):
        record2[key] = record[key]

    record = record2

    for field, value in record.items():
        if field not in ['NetworkCode', 'StationCode']:
            if type(value) is str:
                out.append({'field': field, 'value': value})
            else:
                out.append({'field': field, 'value': str(value)})

    return out  # sorted(out, key=lambda k: k['field'])


class MyApp(object):

    def __init__(self, stdscreen):

        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_WHITE)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)

        global screen
        screen = stdscreen
        self.screen = stdscreen
        curses.curs_set(0)

        main_menu_items = get_records()

        main_menu_items += [{'field': 'Insert new station information record', 'function': selection_main_menu}]

        main_menu = Menu(cnn, main_menu_items, self.screen,
                         'Station information new/edit/delete - %s.%s' % (stn['NetworkCode'], stn['StationCode']))

        main_menu.display()


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Plot ETM for stations in the database')

    parser.add_argument('stn', type=str, nargs=1, help="Station name given in net.stnm format.")

    args = parser.parse_args()

    stn = args.stn[0]

    if '.' in stn:
        rs = cnn.query(
            'SELECT * FROM stations WHERE "NetworkCode" = \'%s\' AND "StationCode" = \'%s\' '
            'ORDER BY "NetworkCode", "StationCode"' % (stn.split('.')[0], stn.split('.')[1]))
    else:
        rs = cnn.query(
            'SELECT * FROM stations WHERE "StationCode" = \'%s\' ORDER BY "NetworkCode", "StationCode"' % stn)

    if rs.ntuples() == 0:
        print('ERROR: Station code not found!')
        exit()
    elif rs.ntuples() > 1:
        print('ERROR: More than one station found! Use net.stnm instead of stnm')
        exit()
    else:
        stn = rs.dictresult()[0]

    curses.wrapper(MyApp)
