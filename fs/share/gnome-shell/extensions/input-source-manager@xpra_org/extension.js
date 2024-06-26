/* extension.js
 *
 * Copyright (C) 2024 Graph Inc.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const { Gio } = imports.gi;
const { getInputSourceManager } = imports.ui.status.keyboard;

const XMLInterface = `<node>
  <interface name="xpra_org.InputSourceManager">
    <method name="Activate">
      <arg type="i" direction="in" name="index" />
      <arg type="b" direction="out" name="success" />
      <arg type="s" direction="out" name="error" />
    </method>
    <method name="List">
      <arg type="b" direction="out" name="success" />
      <arg type="s" direction="out" name="inputSources" />
    </method>
  </interface>
</node>
`;

function init(meta) {
    return new InputSourceManagerInterface();
}

class InputSourceManagerInterface {
    enable() {
        this._ism = new ISMWrapper();
        this._dbusObj= Gio.DBusExportedObject.wrapJSObject(XMLInterface, this._ism);
        this._dbusObj.export(Gio.DBus.session, '/org/xpra/InputSourceManager');
    }

    disable() {
        if (this._dbusObj) {
            this._dbusObj.unexport();
            this._dbusObj= null;
        }
        this._ism = null;
    }
}

class ISMWrapper {
    Activate(index) {
        const inputSources = getInputSourceManager().inputSources;
        const len = inputSources.length
        if (index < 0 || index >= len) {
            return [false, `index (${index}) must be in [0, ${len})`];
        }
        inputSources[index].activate();
        return [true, `input source with index ${index} is activated`];
    }

    List() {
        const inputSources = getInputSourceManager().inputSources;
        return [true, JSON.stringify(inputSources)];
    }
}
