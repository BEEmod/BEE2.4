

/* this ALWAYS GENERATED file contains the definitions for the interfaces */


 /* File created by MIDL compiler version 8.01.0622 */
/* at Tue Jan 19 13:14:07 2038
 */
/* Compiler settings for ITaskbarList.idl:
    Oicf, W1, Zp8, env=Win32 (32b run), target_arch=X86 8.01.0622 
    protocol : dce , ms_ext, c_ext, robust
    error checks: allocation ref bounds_check enum stub_data 
    VC __declspec() decoration level: 
         __declspec(uuid()), __declspec(selectany), __declspec(novtable)
         DECLSPEC_UUID(), MIDL_INTERFACE()
*/
/* @@MIDL_FILE_HEADING(  ) */

#pragma warning( disable: 4049 )  /* more than 64k source lines */


/* verify that the <rpcndr.h> version is high enough to compile this file*/
#ifndef __REQUIRED_RPCNDR_H_VERSION__
#define __REQUIRED_RPCNDR_H_VERSION__ 475
#endif

#include "rpc.h"
#include "rpcndr.h"

#ifndef __RPCNDR_H_VERSION__
#error this stub requires an updated version of <rpcndr.h>
#endif /* __RPCNDR_H_VERSION__ */

#ifndef COM_NO_WINDOWS_H
#include "windows.h"
#include "ole2.h"
#endif /*COM_NO_WINDOWS_H*/

#ifndef __ITaskbarList_h__
#define __ITaskbarList_h__

#if defined(_MSC_VER) && (_MSC_VER >= 1020)
#pragma once
#endif

/* Forward Declarations */ 

#ifndef __ITaskbarList_FWD_DEFINED__
#define __ITaskbarList_FWD_DEFINED__
typedef interface ITaskbarList ITaskbarList;

#endif 	/* __ITaskbarList_FWD_DEFINED__ */


#ifndef __ITaskbarList2_FWD_DEFINED__
#define __ITaskbarList2_FWD_DEFINED__
typedef interface ITaskbarList2 ITaskbarList2;

#endif 	/* __ITaskbarList2_FWD_DEFINED__ */


#ifndef __ITaskbarList3_FWD_DEFINED__
#define __ITaskbarList3_FWD_DEFINED__
typedef interface ITaskbarList3 ITaskbarList3;

#endif 	/* __ITaskbarList3_FWD_DEFINED__ */


/* header files for imported files */
#include "objidl.h"
#include "oleidl.h"
#include "oaidl.h"
#include "docobj.h"
#include "shtypes.h"
#include "comcat.h"
#include "propidl.h"
#include "prsht.h"
#include "propsys.h"
#include "ObjectArray.h"

#ifdef __cplusplus
extern "C"{
#endif 


#ifndef __ITaskbarList_INTERFACE_DEFINED__
#define __ITaskbarList_INTERFACE_DEFINED__

/* interface ITaskbarList */
/* [object][uuid] */ 


EXTERN_C const IID IID_ITaskbarList;

#if defined(__cplusplus) && !defined(CINTERFACE)
    
    MIDL_INTERFACE("56FDF342-FD6D-11d0-958A-006097C9A090")
    ITaskbarList : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE HrInit( void) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE AddTab( 
            /* [in] */ HWND hwnd) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE DeleteTab( 
            /* [in] */ HWND hwnd) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE ActivateTab( 
            /* [in] */ HWND hwnd) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetActiveAlt( 
            /* [in] */ HWND hwnd) = 0;
        
    };
    
    
#else 	/* C style interface */

    typedef struct ITaskbarListVtbl
    {
        BEGIN_INTERFACE
        
        HRESULT ( STDMETHODCALLTYPE *QueryInterface )( 
            ITaskbarList * This,
            /* [in] */ REFIID riid,
            /* [annotation][iid_is][out] */ 
            _COM_Outptr_  void **ppvObject);
        
        ULONG ( STDMETHODCALLTYPE *AddRef )( 
            ITaskbarList * This);
        
        ULONG ( STDMETHODCALLTYPE *Release )( 
            ITaskbarList * This);
        
        HRESULT ( STDMETHODCALLTYPE *HrInit )( 
            ITaskbarList * This);
        
        HRESULT ( STDMETHODCALLTYPE *AddTab )( 
            ITaskbarList * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *DeleteTab )( 
            ITaskbarList * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *ActivateTab )( 
            ITaskbarList * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *SetActiveAlt )( 
            ITaskbarList * This,
            /* [in] */ HWND hwnd);
        
        END_INTERFACE
    } ITaskbarListVtbl;

    interface ITaskbarList
    {
        CONST_VTBL struct ITaskbarListVtbl *lpVtbl;
    };

    

#ifdef COBJMACROS


#define ITaskbarList_QueryInterface(This,riid,ppvObject)	\
    ( (This)->lpVtbl -> QueryInterface(This,riid,ppvObject) ) 

#define ITaskbarList_AddRef(This)	\
    ( (This)->lpVtbl -> AddRef(This) ) 

#define ITaskbarList_Release(This)	\
    ( (This)->lpVtbl -> Release(This) ) 


#define ITaskbarList_HrInit(This)	\
    ( (This)->lpVtbl -> HrInit(This) ) 

#define ITaskbarList_AddTab(This,hwnd)	\
    ( (This)->lpVtbl -> AddTab(This,hwnd) ) 

#define ITaskbarList_DeleteTab(This,hwnd)	\
    ( (This)->lpVtbl -> DeleteTab(This,hwnd) ) 

#define ITaskbarList_ActivateTab(This,hwnd)	\
    ( (This)->lpVtbl -> ActivateTab(This,hwnd) ) 

#define ITaskbarList_SetActiveAlt(This,hwnd)	\
    ( (This)->lpVtbl -> SetActiveAlt(This,hwnd) ) 

#endif /* COBJMACROS */


#endif 	/* C style interface */




#endif 	/* __ITaskbarList_INTERFACE_DEFINED__ */


#ifndef __ITaskbarList2_INTERFACE_DEFINED__
#define __ITaskbarList2_INTERFACE_DEFINED__

/* interface ITaskbarList2 */
/* [object][uuid] */ 


EXTERN_C const IID IID_ITaskbarList2;

#if defined(__cplusplus) && !defined(CINTERFACE)
    
    MIDL_INTERFACE("602D4995-B13A-429b-A66E-1935E44F4317")
    ITaskbarList2 : public ITaskbarList
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE MarkFullscreenWindow( 
            /* [in] */ HWND hwnd,
            /* [in] */ BOOL fFullscreen) = 0;
        
    };
    
    
#else 	/* C style interface */

    typedef struct ITaskbarList2Vtbl
    {
        BEGIN_INTERFACE
        
        HRESULT ( STDMETHODCALLTYPE *QueryInterface )( 
            ITaskbarList2 * This,
            /* [in] */ REFIID riid,
            /* [annotation][iid_is][out] */ 
            _COM_Outptr_  void **ppvObject);
        
        ULONG ( STDMETHODCALLTYPE *AddRef )( 
            ITaskbarList2 * This);
        
        ULONG ( STDMETHODCALLTYPE *Release )( 
            ITaskbarList2 * This);
        
        HRESULT ( STDMETHODCALLTYPE *HrInit )( 
            ITaskbarList2 * This);
        
        HRESULT ( STDMETHODCALLTYPE *AddTab )( 
            ITaskbarList2 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *DeleteTab )( 
            ITaskbarList2 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *ActivateTab )( 
            ITaskbarList2 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *SetActiveAlt )( 
            ITaskbarList2 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *MarkFullscreenWindow )( 
            ITaskbarList2 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ BOOL fFullscreen);
        
        END_INTERFACE
    } ITaskbarList2Vtbl;

    interface ITaskbarList2
    {
        CONST_VTBL struct ITaskbarList2Vtbl *lpVtbl;
    };

    

#ifdef COBJMACROS


#define ITaskbarList2_QueryInterface(This,riid,ppvObject)	\
    ( (This)->lpVtbl -> QueryInterface(This,riid,ppvObject) ) 

#define ITaskbarList2_AddRef(This)	\
    ( (This)->lpVtbl -> AddRef(This) ) 

#define ITaskbarList2_Release(This)	\
    ( (This)->lpVtbl -> Release(This) ) 


#define ITaskbarList2_HrInit(This)	\
    ( (This)->lpVtbl -> HrInit(This) ) 

#define ITaskbarList2_AddTab(This,hwnd)	\
    ( (This)->lpVtbl -> AddTab(This,hwnd) ) 

#define ITaskbarList2_DeleteTab(This,hwnd)	\
    ( (This)->lpVtbl -> DeleteTab(This,hwnd) ) 

#define ITaskbarList2_ActivateTab(This,hwnd)	\
    ( (This)->lpVtbl -> ActivateTab(This,hwnd) ) 

#define ITaskbarList2_SetActiveAlt(This,hwnd)	\
    ( (This)->lpVtbl -> SetActiveAlt(This,hwnd) ) 


#define ITaskbarList2_MarkFullscreenWindow(This,hwnd,fFullscreen)	\
    ( (This)->lpVtbl -> MarkFullscreenWindow(This,hwnd,fFullscreen) ) 

#endif /* COBJMACROS */


#endif 	/* C style interface */




#endif 	/* __ITaskbarList2_INTERFACE_DEFINED__ */


/* interface __MIDL_itf_ITaskbarList_0000_0002 */
/* [local] */ 

#ifdef MIDL_PASS
typedef IUnknown *HIMAGELIST;

#endif
typedef /* [v1_enum] */ 
enum THUMBBUTTONFLAGS
    {
        THBF_ENABLED	= 0,
        THBF_DISABLED	= 0x1,
        THBF_DISMISSONCLICK	= 0x2,
        THBF_NOBACKGROUND	= 0x4,
        THBF_HIDDEN	= 0x8,
        THBF_NONINTERACTIVE	= 0x10
    } 	THUMBBUTTONFLAGS;

DEFINE_ENUM_FLAG_OPERATORS(THUMBBUTTONFLAGS)
typedef /* [v1_enum] */ 
enum THUMBBUTTONMASK
    {
        THB_BITMAP	= 0x1,
        THB_ICON	= 0x2,
        THB_TOOLTIP	= 0x4,
        THB_FLAGS	= 0x8
    } 	THUMBBUTTONMASK;

DEFINE_ENUM_FLAG_OPERATORS(THUMBBUTTONMASK)
#include <pshpack8.h>
typedef struct THUMBBUTTON
    {
    THUMBBUTTONMASK dwMask;
    UINT iId;
    UINT iBitmap;
    HICON hIcon;
    WCHAR szTip[ 260 ];
    THUMBBUTTONFLAGS dwFlags;
    } 	THUMBBUTTON;

typedef struct THUMBBUTTON *LPTHUMBBUTTON;

#include <poppack.h>
#define THBN_CLICKED        0x1800


extern RPC_IF_HANDLE __MIDL_itf_ITaskbarList_0000_0002_v0_0_c_ifspec;
extern RPC_IF_HANDLE __MIDL_itf_ITaskbarList_0000_0002_v0_0_s_ifspec;

#ifndef __ITaskbarList3_INTERFACE_DEFINED__
#define __ITaskbarList3_INTERFACE_DEFINED__

/* interface ITaskbarList3 */
/* [object][uuid] */ 

typedef /* [v1_enum] */ 
enum TBPFLAG
    {
        TBPF_NOPROGRESS	= 0,
        TBPF_INDETERMINATE	= 0x1,
        TBPF_NORMAL	= 0x2,
        TBPF_ERROR	= 0x4,
        TBPF_PAUSED	= 0x8
    } 	TBPFLAG;

DEFINE_ENUM_FLAG_OPERATORS(TBPFLAG)

EXTERN_C const IID IID_ITaskbarList3;

#if defined(__cplusplus) && !defined(CINTERFACE)
    
    MIDL_INTERFACE("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf")
    ITaskbarList3 : public ITaskbarList2
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE SetProgressValue( 
            /* [in] */ HWND hwnd,
            /* [in] */ ULONGLONG ullCompleted,
            /* [in] */ ULONGLONG ullTotal) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetProgressState( 
            /* [in] */ HWND hwnd,
            /* [in] */ TBPFLAG tbpFlags) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE RegisterTab( 
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndMDI) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE UnregisterTab( 
            /* [in] */ HWND hwndTab) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetTabOrder( 
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndInsertBefore) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetTabActive( 
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndMDI,
            /* [in] */ DWORD dwReserved) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE ThumbBarAddButtons( 
            /* [in] */ HWND hwnd,
            /* [in] */ UINT cButtons,
            /* [size_is][in] */ LPTHUMBBUTTON pButton) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE ThumbBarUpdateButtons( 
            /* [in] */ HWND hwnd,
            /* [in] */ UINT cButtons,
            /* [size_is][in] */ LPTHUMBBUTTON pButton) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE ThumbBarSetImageList( 
            /* [in] */ HWND hwnd,
            /* [in] */ HIMAGELIST himl) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetOverlayIcon( 
            /* [in] */ HWND hwnd,
            /* [in] */ HICON hIcon,
            /* [string][unique][in] */ LPCWSTR pszDescription) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetThumbnailTooltip( 
            /* [in] */ HWND hwnd,
            /* [string][unique][in] */ LPCWSTR pszTip) = 0;
        
        virtual HRESULT STDMETHODCALLTYPE SetThumbnailClip( 
            /* [in] */ HWND hwnd,
            /* [in] */ RECT *prcClip) = 0;
        
    };
    
    
#else 	/* C style interface */

    typedef struct ITaskbarList3Vtbl
    {
        BEGIN_INTERFACE
        
        HRESULT ( STDMETHODCALLTYPE *QueryInterface )( 
            ITaskbarList3 * This,
            /* [in] */ REFIID riid,
            /* [annotation][iid_is][out] */ 
            _COM_Outptr_  void **ppvObject);
        
        ULONG ( STDMETHODCALLTYPE *AddRef )( 
            ITaskbarList3 * This);
        
        ULONG ( STDMETHODCALLTYPE *Release )( 
            ITaskbarList3 * This);
        
        HRESULT ( STDMETHODCALLTYPE *HrInit )( 
            ITaskbarList3 * This);
        
        HRESULT ( STDMETHODCALLTYPE *AddTab )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *DeleteTab )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *ActivateTab )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *SetActiveAlt )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd);
        
        HRESULT ( STDMETHODCALLTYPE *MarkFullscreenWindow )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ BOOL fFullscreen);
        
        HRESULT ( STDMETHODCALLTYPE *SetProgressValue )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ ULONGLONG ullCompleted,
            /* [in] */ ULONGLONG ullTotal);
        
        HRESULT ( STDMETHODCALLTYPE *SetProgressState )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ TBPFLAG tbpFlags);
        
        HRESULT ( STDMETHODCALLTYPE *RegisterTab )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndMDI);
        
        HRESULT ( STDMETHODCALLTYPE *UnregisterTab )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwndTab);
        
        HRESULT ( STDMETHODCALLTYPE *SetTabOrder )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndInsertBefore);
        
        HRESULT ( STDMETHODCALLTYPE *SetTabActive )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwndTab,
            /* [in] */ HWND hwndMDI,
            /* [in] */ DWORD dwReserved);
        
        HRESULT ( STDMETHODCALLTYPE *ThumbBarAddButtons )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ UINT cButtons,
            /* [size_is][in] */ LPTHUMBBUTTON pButton);
        
        HRESULT ( STDMETHODCALLTYPE *ThumbBarUpdateButtons )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ UINT cButtons,
            /* [size_is][in] */ LPTHUMBBUTTON pButton);
        
        HRESULT ( STDMETHODCALLTYPE *ThumbBarSetImageList )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ HIMAGELIST himl);
        
        HRESULT ( STDMETHODCALLTYPE *SetOverlayIcon )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ HICON hIcon,
            /* [string][unique][in] */ LPCWSTR pszDescription);
        
        HRESULT ( STDMETHODCALLTYPE *SetThumbnailTooltip )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [string][unique][in] */ LPCWSTR pszTip);
        
        HRESULT ( STDMETHODCALLTYPE *SetThumbnailClip )( 
            ITaskbarList3 * This,
            /* [in] */ HWND hwnd,
            /* [in] */ RECT *prcClip);
        
        END_INTERFACE
    } ITaskbarList3Vtbl;

    interface ITaskbarList3
    {
        CONST_VTBL struct ITaskbarList3Vtbl *lpVtbl;
    };

    

#ifdef COBJMACROS


#define ITaskbarList3_QueryInterface(This,riid,ppvObject)	\
    ( (This)->lpVtbl -> QueryInterface(This,riid,ppvObject) ) 

#define ITaskbarList3_AddRef(This)	\
    ( (This)->lpVtbl -> AddRef(This) ) 

#define ITaskbarList3_Release(This)	\
    ( (This)->lpVtbl -> Release(This) ) 


#define ITaskbarList3_HrInit(This)	\
    ( (This)->lpVtbl -> HrInit(This) ) 

#define ITaskbarList3_AddTab(This,hwnd)	\
    ( (This)->lpVtbl -> AddTab(This,hwnd) ) 

#define ITaskbarList3_DeleteTab(This,hwnd)	\
    ( (This)->lpVtbl -> DeleteTab(This,hwnd) ) 

#define ITaskbarList3_ActivateTab(This,hwnd)	\
    ( (This)->lpVtbl -> ActivateTab(This,hwnd) ) 

#define ITaskbarList3_SetActiveAlt(This,hwnd)	\
    ( (This)->lpVtbl -> SetActiveAlt(This,hwnd) ) 


#define ITaskbarList3_MarkFullscreenWindow(This,hwnd,fFullscreen)	\
    ( (This)->lpVtbl -> MarkFullscreenWindow(This,hwnd,fFullscreen) ) 


#define ITaskbarList3_SetProgressValue(This,hwnd,ullCompleted,ullTotal)	\
    ( (This)->lpVtbl -> SetProgressValue(This,hwnd,ullCompleted,ullTotal) ) 

#define ITaskbarList3_SetProgressState(This,hwnd,tbpFlags)	\
    ( (This)->lpVtbl -> SetProgressState(This,hwnd,tbpFlags) ) 

#define ITaskbarList3_RegisterTab(This,hwndTab,hwndMDI)	\
    ( (This)->lpVtbl -> RegisterTab(This,hwndTab,hwndMDI) ) 

#define ITaskbarList3_UnregisterTab(This,hwndTab)	\
    ( (This)->lpVtbl -> UnregisterTab(This,hwndTab) ) 

#define ITaskbarList3_SetTabOrder(This,hwndTab,hwndInsertBefore)	\
    ( (This)->lpVtbl -> SetTabOrder(This,hwndTab,hwndInsertBefore) ) 

#define ITaskbarList3_SetTabActive(This,hwndTab,hwndMDI,dwReserved)	\
    ( (This)->lpVtbl -> SetTabActive(This,hwndTab,hwndMDI,dwReserved) ) 

#define ITaskbarList3_ThumbBarAddButtons(This,hwnd,cButtons,pButton)	\
    ( (This)->lpVtbl -> ThumbBarAddButtons(This,hwnd,cButtons,pButton) ) 

#define ITaskbarList3_ThumbBarUpdateButtons(This,hwnd,cButtons,pButton)	\
    ( (This)->lpVtbl -> ThumbBarUpdateButtons(This,hwnd,cButtons,pButton) ) 

#define ITaskbarList3_ThumbBarSetImageList(This,hwnd,himl)	\
    ( (This)->lpVtbl -> ThumbBarSetImageList(This,hwnd,himl) ) 

#define ITaskbarList3_SetOverlayIcon(This,hwnd,hIcon,pszDescription)	\
    ( (This)->lpVtbl -> SetOverlayIcon(This,hwnd,hIcon,pszDescription) ) 

#define ITaskbarList3_SetThumbnailTooltip(This,hwnd,pszTip)	\
    ( (This)->lpVtbl -> SetThumbnailTooltip(This,hwnd,pszTip) ) 

#define ITaskbarList3_SetThumbnailClip(This,hwnd,prcClip)	\
    ( (This)->lpVtbl -> SetThumbnailClip(This,hwnd,prcClip) ) 

#endif /* COBJMACROS */


#endif 	/* C style interface */




#endif 	/* __ITaskbarList3_INTERFACE_DEFINED__ */


/* Additional Prototypes for ALL interfaces */

unsigned long             __RPC_USER  HICON_UserSize(     unsigned long *, unsigned long            , HICON * ); 
unsigned char * __RPC_USER  HICON_UserMarshal(  unsigned long *, unsigned char *, HICON * ); 
unsigned char * __RPC_USER  HICON_UserUnmarshal(unsigned long *, unsigned char *, HICON * ); 
void                      __RPC_USER  HICON_UserFree(     unsigned long *, HICON * ); 

unsigned long             __RPC_USER  HWND_UserSize(     unsigned long *, unsigned long            , HWND * ); 
unsigned char * __RPC_USER  HWND_UserMarshal(  unsigned long *, unsigned char *, HWND * ); 
unsigned char * __RPC_USER  HWND_UserUnmarshal(unsigned long *, unsigned char *, HWND * ); 
void                      __RPC_USER  HWND_UserFree(     unsigned long *, HWND * ); 

/* end of Additional Prototypes */

#ifdef __cplusplus
}
#endif

#endif


