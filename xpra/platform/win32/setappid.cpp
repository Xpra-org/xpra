// THIS CODE AND INFORMATION IS PROVIDED "AS IS" WITHOUT WARRANTY OF
// ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING BUT NOT LIMITED TO
// THE IMPLIED WARRANTIES OF MERCHANTABILITY AND/OR FITNESS FOR A
// PARTICULAR PURPOSE.
//
// Copyright (c) Microsoft Corporation. All rights reserved

#define NTDDI_VERSION NTDDI_WIN7  // Specifies that the minimum required platform is Windows 7.
#define WIN32_LEAN_AND_MEAN       // Exclude rarely-used stuff from Windows headers

#include <windows.h>
#include <shobjidl.h>
#include <propkey.h>
#include <propvarutil.h>
#include <shellapi.h>

#include <stdio.h>

namespace utility
{
	// Sets the specified AppUserModelID on the window, or removes the value if a negative index is provided
	long SetAppID(HWND hWnd, PCWSTR pszAppID)
	{
		// Obtain the window's property store.  This IPropertyStore implementation does not require
		// IPropertyStore::Commit to be called - values are updated on the window immediately.  Setting a
		// property on a window via this IPropertyStore allocates global storage space for the property value
		// that is not automatically cleaned up upon window destruction or process termination, thus all
		// properties set on a window should be removed in response to WM_DESTROY.
		IPropertyStore *pps;
		HRESULT hr = SHGetPropertyStoreForWindow(hWnd, IID_PPV_ARGS(&pps));
#ifdef DEBUG
		printf("SHGetPropertyStoreForWindow(%p, %p)=%li\n", hWnd, pps, hr);
#endif
		if (SUCCEEDED(hr))
		{
			PROPVARIANT pv;
			if (pszAppID)
			{
				hr = InitPropVariantFromString(pszAppID, &pv);
#ifdef DEBUG
				printf("InitPropVariantFromString(%p, %p)=%li\n", pszAppID, &pv, hr);
#endif
			}
			else
			{
				// Sets the variant type as VT_EMPTY, which removes the property from the window, if present
				PropVariantInit(&pv);
			}
			if (SUCCEEDED(hr))
			{
				// Sets the PKEY_AppUserModel_ID property, which controls how windows are grouped into buttons
				// on the taskbar.  If the window needed other PKEY_AppUserModel_* properties to be set, they
				// should be set BEFORE setting PKEY_AppUserModel_ID, as the taskbar will only respond to
				// updates of PKEY_AppUserModel_ID.
				hr = pps->SetValue(PKEY_AppUserModel_ID, pv);
#ifdef DEBUG
				printf("IPropertyStore.SetValue(PKEY_AppUserModel_ID, %p)=%li\n", &pv, hr);
#endif
				PropVariantClear(&pv);
			}
			pps->Release();
		}
#ifdef DEBUG
		if (hr!=0) {
			char *err;
			if (FormatMessage(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM,
							   NULL,
							   hr,
							   MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT), // default language
							   (LPTSTR) &err,
							   0,
							   NULL)) {
			        printf("Error: %s", err);
					LocalFree(err);
			}
		}
#endif
		return hr;
	}
}
