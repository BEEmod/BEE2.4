

/* this ALWAYS GENERATED file contains the proxy stub code */


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

#if !defined(_M_IA64) && !defined(_M_AMD64) && !defined(_ARM_)


#pragma warning( disable: 4049 )  /* more than 64k source lines */
#if _MSC_VER >= 1200
#pragma warning(push)
#endif

#pragma warning( disable: 4211 )  /* redefine extern to static */
#pragma warning( disable: 4232 )  /* dllimport identity*/
#pragma warning( disable: 4024 )  /* array to pointer mapping*/
#pragma warning( disable: 4152 )  /* function/data pointer conversion in expression */
#pragma warning( disable: 4100 ) /* unreferenced arguments in x86 call */

#pragma optimize("", off ) 

#define USE_STUBLESS_PROXY


/* verify that the <rpcproxy.h> version is high enough to compile this file*/
#ifndef __REDQ_RPCPROXY_H_VERSION__
#define __REQUIRED_RPCPROXY_H_VERSION__ 475
#endif


#include "rpcproxy.h"
#ifndef __RPCPROXY_H_VERSION__
#error this stub requires an updated version of <rpcproxy.h>
#endif /* __RPCPROXY_H_VERSION__ */


#include "ITaskbarList.h"

#define TYPE_FORMAT_STRING_SIZE   137                               
#define PROC_FORMAT_STRING_SIZE   745                               
#define EXPR_FORMAT_STRING_SIZE   1                                 
#define TRANSMIT_AS_TABLE_SIZE    0            
#define WIRE_MARSHAL_TABLE_SIZE   2            

typedef struct _ITaskbarList_MIDL_TYPE_FORMAT_STRING
    {
    short          Pad;
    unsigned char  Format[ TYPE_FORMAT_STRING_SIZE ];
    } ITaskbarList_MIDL_TYPE_FORMAT_STRING;

typedef struct _ITaskbarList_MIDL_PROC_FORMAT_STRING
    {
    short          Pad;
    unsigned char  Format[ PROC_FORMAT_STRING_SIZE ];
    } ITaskbarList_MIDL_PROC_FORMAT_STRING;

typedef struct _ITaskbarList_MIDL_EXPR_FORMAT_STRING
    {
    long          Pad;
    unsigned char  Format[ EXPR_FORMAT_STRING_SIZE ];
    } ITaskbarList_MIDL_EXPR_FORMAT_STRING;


static const RPC_SYNTAX_IDENTIFIER  _RpcTransferSyntax = 
{{0x8A885D04,0x1CEB,0x11C9,{0x9F,0xE8,0x08,0x00,0x2B,0x10,0x48,0x60}},{2,0}};


extern const ITaskbarList_MIDL_TYPE_FORMAT_STRING ITaskbarList__MIDL_TypeFormatString;
extern const ITaskbarList_MIDL_PROC_FORMAT_STRING ITaskbarList__MIDL_ProcFormatString;
extern const ITaskbarList_MIDL_EXPR_FORMAT_STRING ITaskbarList__MIDL_ExprFormatString;


extern const MIDL_STUB_DESC Object_StubDesc;


extern const MIDL_SERVER_INFO ITaskbarList_ServerInfo;
extern const MIDL_STUBLESS_PROXY_INFO ITaskbarList_ProxyInfo;


extern const MIDL_STUB_DESC Object_StubDesc;


extern const MIDL_SERVER_INFO ITaskbarList2_ServerInfo;
extern const MIDL_STUBLESS_PROXY_INFO ITaskbarList2_ProxyInfo;


extern const MIDL_STUB_DESC Object_StubDesc;


extern const MIDL_SERVER_INFO ITaskbarList3_ServerInfo;
extern const MIDL_STUBLESS_PROXY_INFO ITaskbarList3_ProxyInfo;


extern const USER_MARSHAL_ROUTINE_QUADRUPLE UserMarshalRoutines[ WIRE_MARSHAL_TABLE_SIZE ];

#if !defined(__RPC_WIN32__)
#error  Invalid build platform for this stub.
#endif

#if !(TARGET_IS_NT50_OR_LATER)
#error You need Windows 2000 or later to run this stub because it uses these features:
#error   /robust command line switch.
#error However, your C/C++ compilation flags indicate you intend to run this app on earlier systems.
#error This app will fail with the RPC_X_WRONG_STUB_VERSION error.
#endif


static const ITaskbarList_MIDL_PROC_FORMAT_STRING ITaskbarList__MIDL_ProcFormatString =
    {
        0,
        {

	/* Procedure HrInit */

			0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/*  2 */	NdrFcLong( 0x0 ),	/* 0 */
/*  6 */	NdrFcShort( 0x3 ),	/* 3 */
/*  8 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 10 */	NdrFcShort( 0x0 ),	/* 0 */
/* 12 */	NdrFcShort( 0x8 ),	/* 8 */
/* 14 */	0x44,		/* Oi2 Flags:  has return, has ext, */
			0x1,		/* 1 */
/* 16 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 18 */	NdrFcShort( 0x0 ),	/* 0 */
/* 20 */	NdrFcShort( 0x0 ),	/* 0 */
/* 22 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Return value */

/* 24 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 26 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 28 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure AddTab */

/* 30 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 32 */	NdrFcLong( 0x0 ),	/* 0 */
/* 36 */	NdrFcShort( 0x4 ),	/* 4 */
/* 38 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 40 */	NdrFcShort( 0x0 ),	/* 0 */
/* 42 */	NdrFcShort( 0x8 ),	/* 8 */
/* 44 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x2,		/* 2 */
/* 46 */	0x8,		/* 8 */
			0x5,		/* Ext Flags:  new corr desc, srv corr check, */
/* 48 */	NdrFcShort( 0x0 ),	/* 0 */
/* 50 */	NdrFcShort( 0x1 ),	/* 1 */
/* 52 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 54 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 56 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 58 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 60 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 62 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 64 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure DeleteTab */

/* 66 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 68 */	NdrFcLong( 0x0 ),	/* 0 */
/* 72 */	NdrFcShort( 0x5 ),	/* 5 */
/* 74 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 76 */	NdrFcShort( 0x0 ),	/* 0 */
/* 78 */	NdrFcShort( 0x8 ),	/* 8 */
/* 80 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x2,		/* 2 */
/* 82 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 84 */	NdrFcShort( 0x0 ),	/* 0 */
/* 86 */	NdrFcShort( 0x0 ),	/* 0 */
/* 88 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 90 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 92 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 94 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 96 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 98 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 100 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure ActivateTab */

/* 102 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 104 */	NdrFcLong( 0x0 ),	/* 0 */
/* 108 */	NdrFcShort( 0x6 ),	/* 6 */
/* 110 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 112 */	NdrFcShort( 0x0 ),	/* 0 */
/* 114 */	NdrFcShort( 0x8 ),	/* 8 */
/* 116 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x2,		/* 2 */
/* 118 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 120 */	NdrFcShort( 0x0 ),	/* 0 */
/* 122 */	NdrFcShort( 0x0 ),	/* 0 */
/* 124 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 126 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 128 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 130 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 132 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 134 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 136 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetActiveAlt */

/* 138 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 140 */	NdrFcLong( 0x0 ),	/* 0 */
/* 144 */	NdrFcShort( 0x7 ),	/* 7 */
/* 146 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 148 */	NdrFcShort( 0x0 ),	/* 0 */
/* 150 */	NdrFcShort( 0x8 ),	/* 8 */
/* 152 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x2,		/* 2 */
/* 154 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 156 */	NdrFcShort( 0x0 ),	/* 0 */
/* 158 */	NdrFcShort( 0x0 ),	/* 0 */
/* 160 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 162 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 164 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 166 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 168 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 170 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 172 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure MarkFullscreenWindow */

/* 174 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 176 */	NdrFcLong( 0x0 ),	/* 0 */
/* 180 */	NdrFcShort( 0x8 ),	/* 8 */
/* 182 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 184 */	NdrFcShort( 0x8 ),	/* 8 */
/* 186 */	NdrFcShort( 0x8 ),	/* 8 */
/* 188 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 190 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 192 */	NdrFcShort( 0x0 ),	/* 0 */
/* 194 */	NdrFcShort( 0x0 ),	/* 0 */
/* 196 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 198 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 200 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 202 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter fFullscreen */

/* 204 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 206 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 208 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Return value */

/* 210 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 212 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 214 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetProgressValue */

/* 216 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 218 */	NdrFcLong( 0x0 ),	/* 0 */
/* 222 */	NdrFcShort( 0x9 ),	/* 9 */
/* 224 */	NdrFcShort( 0x1c ),	/* x86 Stack size/offset = 28 */
/* 226 */	NdrFcShort( 0x20 ),	/* 32 */
/* 228 */	NdrFcShort( 0x8 ),	/* 8 */
/* 230 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x4,		/* 4 */
/* 232 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 234 */	NdrFcShort( 0x0 ),	/* 0 */
/* 236 */	NdrFcShort( 0x0 ),	/* 0 */
/* 238 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 240 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 242 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 244 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter ullCompleted */

/* 246 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 248 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 250 */	0xb,		/* FC_HYPER */
			0x0,		/* 0 */

	/* Parameter ullTotal */

/* 252 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 254 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 256 */	0xb,		/* FC_HYPER */
			0x0,		/* 0 */

	/* Return value */

/* 258 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 260 */	NdrFcShort( 0x18 ),	/* x86 Stack size/offset = 24 */
/* 262 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetProgressState */

/* 264 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 266 */	NdrFcLong( 0x0 ),	/* 0 */
/* 270 */	NdrFcShort( 0xa ),	/* 10 */
/* 272 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 274 */	NdrFcShort( 0x8 ),	/* 8 */
/* 276 */	NdrFcShort( 0x8 ),	/* 8 */
/* 278 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 280 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 282 */	NdrFcShort( 0x0 ),	/* 0 */
/* 284 */	NdrFcShort( 0x0 ),	/* 0 */
/* 286 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 288 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 290 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 292 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter tbpFlags */

/* 294 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 296 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 298 */	0xe,		/* FC_ENUM32 */
			0x0,		/* 0 */

	/* Return value */

/* 300 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 302 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 304 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure RegisterTab */

/* 306 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 308 */	NdrFcLong( 0x0 ),	/* 0 */
/* 312 */	NdrFcShort( 0xb ),	/* 11 */
/* 314 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 316 */	NdrFcShort( 0x0 ),	/* 0 */
/* 318 */	NdrFcShort( 0x8 ),	/* 8 */
/* 320 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 322 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 324 */	NdrFcShort( 0x0 ),	/* 0 */
/* 326 */	NdrFcShort( 0x0 ),	/* 0 */
/* 328 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwndTab */

/* 330 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 332 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 334 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter hwndMDI */

/* 336 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 338 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 340 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 342 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 344 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 346 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure UnregisterTab */

/* 348 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 350 */	NdrFcLong( 0x0 ),	/* 0 */
/* 354 */	NdrFcShort( 0xc ),	/* 12 */
/* 356 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 358 */	NdrFcShort( 0x0 ),	/* 0 */
/* 360 */	NdrFcShort( 0x8 ),	/* 8 */
/* 362 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x2,		/* 2 */
/* 364 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 366 */	NdrFcShort( 0x0 ),	/* 0 */
/* 368 */	NdrFcShort( 0x0 ),	/* 0 */
/* 370 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwndTab */

/* 372 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 374 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 376 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 378 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 380 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 382 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetTabOrder */

/* 384 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 386 */	NdrFcLong( 0x0 ),	/* 0 */
/* 390 */	NdrFcShort( 0xd ),	/* 13 */
/* 392 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 394 */	NdrFcShort( 0x0 ),	/* 0 */
/* 396 */	NdrFcShort( 0x8 ),	/* 8 */
/* 398 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 400 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 402 */	NdrFcShort( 0x0 ),	/* 0 */
/* 404 */	NdrFcShort( 0x0 ),	/* 0 */
/* 406 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwndTab */

/* 408 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 410 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 412 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter hwndInsertBefore */

/* 414 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 416 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 418 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Return value */

/* 420 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 422 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 424 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetTabActive */

/* 426 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 428 */	NdrFcLong( 0x0 ),	/* 0 */
/* 432 */	NdrFcShort( 0xe ),	/* 14 */
/* 434 */	NdrFcShort( 0x14 ),	/* x86 Stack size/offset = 20 */
/* 436 */	NdrFcShort( 0x8 ),	/* 8 */
/* 438 */	NdrFcShort( 0x8 ),	/* 8 */
/* 440 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x4,		/* 4 */
/* 442 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 444 */	NdrFcShort( 0x0 ),	/* 0 */
/* 446 */	NdrFcShort( 0x0 ),	/* 0 */
/* 448 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwndTab */

/* 450 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 452 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 454 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter hwndMDI */

/* 456 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 458 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 460 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter dwReserved */

/* 462 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 464 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 466 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Return value */

/* 468 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 470 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 472 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure ThumbBarAddButtons */

/* 474 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 476 */	NdrFcLong( 0x0 ),	/* 0 */
/* 480 */	NdrFcShort( 0xf ),	/* 15 */
/* 482 */	NdrFcShort( 0x14 ),	/* x86 Stack size/offset = 20 */
/* 484 */	NdrFcShort( 0x8 ),	/* 8 */
/* 486 */	NdrFcShort( 0x8 ),	/* 8 */
/* 488 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x4,		/* 4 */
/* 490 */	0x8,		/* 8 */
			0x5,		/* Ext Flags:  new corr desc, srv corr check, */
/* 492 */	NdrFcShort( 0x0 ),	/* 0 */
/* 494 */	NdrFcShort( 0x1 ),	/* 1 */
/* 496 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 498 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 500 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 502 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter cButtons */

/* 504 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 506 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 508 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Parameter pButton */

/* 510 */	NdrFcShort( 0x10b ),	/* Flags:  must size, must free, in, simple ref, */
/* 512 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 514 */	NdrFcShort( 0x4e ),	/* Type Offset=78 */

	/* Return value */

/* 516 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 518 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 520 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure ThumbBarUpdateButtons */

/* 522 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 524 */	NdrFcLong( 0x0 ),	/* 0 */
/* 528 */	NdrFcShort( 0x10 ),	/* 16 */
/* 530 */	NdrFcShort( 0x14 ),	/* x86 Stack size/offset = 20 */
/* 532 */	NdrFcShort( 0x8 ),	/* 8 */
/* 534 */	NdrFcShort( 0x8 ),	/* 8 */
/* 536 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x4,		/* 4 */
/* 538 */	0x8,		/* 8 */
			0x5,		/* Ext Flags:  new corr desc, srv corr check, */
/* 540 */	NdrFcShort( 0x0 ),	/* 0 */
/* 542 */	NdrFcShort( 0x1 ),	/* 1 */
/* 544 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 546 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 548 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 550 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter cButtons */

/* 552 */	NdrFcShort( 0x48 ),	/* Flags:  in, base type, */
/* 554 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 556 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Parameter pButton */

/* 558 */	NdrFcShort( 0x10b ),	/* Flags:  must size, must free, in, simple ref, */
/* 560 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 562 */	NdrFcShort( 0x4e ),	/* Type Offset=78 */

	/* Return value */

/* 564 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 566 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 568 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure ThumbBarSetImageList */

/* 570 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 572 */	NdrFcLong( 0x0 ),	/* 0 */
/* 576 */	NdrFcShort( 0x11 ),	/* 17 */
/* 578 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 580 */	NdrFcShort( 0x0 ),	/* 0 */
/* 582 */	NdrFcShort( 0x8 ),	/* 8 */
/* 584 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 586 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 588 */	NdrFcShort( 0x0 ),	/* 0 */
/* 590 */	NdrFcShort( 0x0 ),	/* 0 */
/* 592 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 594 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 596 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 598 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter himl */

/* 600 */	NdrFcShort( 0xb ),	/* Flags:  must size, must free, in, */
/* 602 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 604 */	NdrFcShort( 0x64 ),	/* Type Offset=100 */

	/* Return value */

/* 606 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 608 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 610 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetOverlayIcon */

/* 612 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 614 */	NdrFcLong( 0x0 ),	/* 0 */
/* 618 */	NdrFcShort( 0x12 ),	/* 18 */
/* 620 */	NdrFcShort( 0x14 ),	/* x86 Stack size/offset = 20 */
/* 622 */	NdrFcShort( 0x0 ),	/* 0 */
/* 624 */	NdrFcShort( 0x8 ),	/* 8 */
/* 626 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x4,		/* 4 */
/* 628 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 630 */	NdrFcShort( 0x0 ),	/* 0 */
/* 632 */	NdrFcShort( 0x0 ),	/* 0 */
/* 634 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 636 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 638 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 640 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter hIcon */

/* 642 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 644 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 646 */	NdrFcShort( 0x28 ),	/* Type Offset=40 */

	/* Parameter pszDescription */

/* 648 */	NdrFcShort( 0xb ),	/* Flags:  must size, must free, in, */
/* 650 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 652 */	NdrFcShort( 0x76 ),	/* Type Offset=118 */

	/* Return value */

/* 654 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 656 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 658 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetThumbnailTooltip */

/* 660 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 662 */	NdrFcLong( 0x0 ),	/* 0 */
/* 666 */	NdrFcShort( 0x13 ),	/* 19 */
/* 668 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 670 */	NdrFcShort( 0x0 ),	/* 0 */
/* 672 */	NdrFcShort( 0x8 ),	/* 8 */
/* 674 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 676 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 678 */	NdrFcShort( 0x0 ),	/* 0 */
/* 680 */	NdrFcShort( 0x0 ),	/* 0 */
/* 682 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 684 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 686 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 688 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter pszTip */

/* 690 */	NdrFcShort( 0xb ),	/* Flags:  must size, must free, in, */
/* 692 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 694 */	NdrFcShort( 0x76 ),	/* Type Offset=118 */

	/* Return value */

/* 696 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 698 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 700 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

	/* Procedure SetThumbnailClip */

/* 702 */	0x33,		/* FC_AUTO_HANDLE */
			0x6c,		/* Old Flags:  object, Oi2 */
/* 704 */	NdrFcLong( 0x0 ),	/* 0 */
/* 708 */	NdrFcShort( 0x14 ),	/* 20 */
/* 710 */	NdrFcShort( 0x10 ),	/* x86 Stack size/offset = 16 */
/* 712 */	NdrFcShort( 0x34 ),	/* 52 */
/* 714 */	NdrFcShort( 0x8 ),	/* 8 */
/* 716 */	0x46,		/* Oi2 Flags:  clt must size, has return, has ext, */
			0x3,		/* 3 */
/* 718 */	0x8,		/* 8 */
			0x1,		/* Ext Flags:  new corr desc, */
/* 720 */	NdrFcShort( 0x0 ),	/* 0 */
/* 722 */	NdrFcShort( 0x0 ),	/* 0 */
/* 724 */	NdrFcShort( 0x0 ),	/* 0 */

	/* Parameter hwnd */

/* 726 */	NdrFcShort( 0x8b ),	/* Flags:  must size, must free, in, by val, */
/* 728 */	NdrFcShort( 0x4 ),	/* x86 Stack size/offset = 4 */
/* 730 */	NdrFcShort( 0x1a ),	/* Type Offset=26 */

	/* Parameter prcClip */

/* 732 */	NdrFcShort( 0x10a ),	/* Flags:  must free, in, simple ref, */
/* 734 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 736 */	NdrFcShort( 0x7e ),	/* Type Offset=126 */

	/* Return value */

/* 738 */	NdrFcShort( 0x70 ),	/* Flags:  out, return, base type, */
/* 740 */	NdrFcShort( 0xc ),	/* x86 Stack size/offset = 12 */
/* 742 */	0x8,		/* FC_LONG */
			0x0,		/* 0 */

			0x0
        }
    };

static const ITaskbarList_MIDL_TYPE_FORMAT_STRING ITaskbarList__MIDL_TypeFormatString =
    {
        0,
        {
			NdrFcShort( 0x0 ),	/* 0 */
/*  2 */	
			0x12, 0x0,	/* FC_UP */
/*  4 */	NdrFcShort( 0x2 ),	/* Offset= 2 (6) */
/*  6 */	
			0x2a,		/* FC_ENCAPSULATED_UNION */
			0x48,		/* 72 */
/*  8 */	NdrFcShort( 0x4 ),	/* 4 */
/* 10 */	NdrFcShort( 0x2 ),	/* 2 */
/* 12 */	NdrFcLong( 0x48746457 ),	/* 1215587415 */
/* 16 */	NdrFcShort( 0x8008 ),	/* Simple arm type: FC_LONG */
/* 18 */	NdrFcLong( 0x52746457 ),	/* 1383359575 */
/* 22 */	NdrFcShort( 0x8008 ),	/* Simple arm type: FC_LONG */
/* 24 */	NdrFcShort( 0xffff ),	/* Offset= -1 (23) */
/* 26 */	0xb4,		/* FC_USER_MARSHAL */
			0x83,		/* 131 */
/* 28 */	NdrFcShort( 0x0 ),	/* 0 */
/* 30 */	NdrFcShort( 0x4 ),	/* 4 */
/* 32 */	NdrFcShort( 0x0 ),	/* 0 */
/* 34 */	NdrFcShort( 0xffe0 ),	/* Offset= -32 (2) */
/* 36 */	
			0x11, 0x0,	/* FC_RP */
/* 38 */	NdrFcShort( 0x28 ),	/* Offset= 40 (78) */
/* 40 */	0xb4,		/* FC_USER_MARSHAL */
			0x83,		/* 131 */
/* 42 */	NdrFcShort( 0x1 ),	/* 1 */
/* 44 */	NdrFcShort( 0x4 ),	/* 4 */
/* 46 */	NdrFcShort( 0x0 ),	/* 0 */
/* 48 */	NdrFcShort( 0xffd2 ),	/* Offset= -46 (2) */
/* 50 */	
			0x1d,		/* FC_SMFARRAY */
			0x1,		/* 1 */
/* 52 */	NdrFcShort( 0x208 ),	/* 520 */
/* 54 */	0x5,		/* FC_WCHAR */
			0x5b,		/* FC_END */
/* 56 */	
			0x1a,		/* FC_BOGUS_STRUCT */
			0x3,		/* 3 */
/* 58 */	NdrFcShort( 0x21c ),	/* 540 */
/* 60 */	NdrFcShort( 0x0 ),	/* 0 */
/* 62 */	NdrFcShort( 0x0 ),	/* Offset= 0 (62) */
/* 64 */	0xe,		/* FC_ENUM32 */
			0x8,		/* FC_LONG */
/* 66 */	0x8,		/* FC_LONG */
			0x4c,		/* FC_EMBEDDED_COMPLEX */
/* 68 */	0x0,		/* 0 */
			NdrFcShort( 0xffe3 ),	/* Offset= -29 (40) */
			0x4c,		/* FC_EMBEDDED_COMPLEX */
/* 72 */	0x0,		/* 0 */
			NdrFcShort( 0xffe9 ),	/* Offset= -23 (50) */
			0xe,		/* FC_ENUM32 */
/* 76 */	0x5c,		/* FC_PAD */
			0x5b,		/* FC_END */
/* 78 */	
			0x21,		/* FC_BOGUS_ARRAY */
			0x3,		/* 3 */
/* 80 */	NdrFcShort( 0x0 ),	/* 0 */
/* 82 */	0x29,		/* Corr desc:  parameter, FC_ULONG */
			0x0,		/*  */
/* 84 */	NdrFcShort( 0x8 ),	/* x86 Stack size/offset = 8 */
/* 86 */	NdrFcShort( 0x1 ),	/* Corr flags:  early, */
/* 88 */	NdrFcLong( 0xffffffff ),	/* -1 */
/* 92 */	NdrFcShort( 0x0 ),	/* Corr flags:  */
/* 94 */	0x4c,		/* FC_EMBEDDED_COMPLEX */
			0x0,		/* 0 */
/* 96 */	NdrFcShort( 0xffd8 ),	/* Offset= -40 (56) */
/* 98 */	0x5c,		/* FC_PAD */
			0x5b,		/* FC_END */
/* 100 */	
			0x2f,		/* FC_IP */
			0x5a,		/* FC_CONSTANT_IID */
/* 102 */	NdrFcLong( 0x0 ),	/* 0 */
/* 106 */	NdrFcShort( 0x0 ),	/* 0 */
/* 108 */	NdrFcShort( 0x0 ),	/* 0 */
/* 110 */	0xc0,		/* 192 */
			0x0,		/* 0 */
/* 112 */	0x0,		/* 0 */
			0x0,		/* 0 */
/* 114 */	0x0,		/* 0 */
			0x0,		/* 0 */
/* 116 */	0x0,		/* 0 */
			0x46,		/* 70 */
/* 118 */	
			0x12, 0x8,	/* FC_UP [simple_pointer] */
/* 120 */	
			0x25,		/* FC_C_WSTRING */
			0x5c,		/* FC_PAD */
/* 122 */	
			0x11, 0x0,	/* FC_RP */
/* 124 */	NdrFcShort( 0x2 ),	/* Offset= 2 (126) */
/* 126 */	
			0x15,		/* FC_STRUCT */
			0x3,		/* 3 */
/* 128 */	NdrFcShort( 0x10 ),	/* 16 */
/* 130 */	0x8,		/* FC_LONG */
			0x8,		/* FC_LONG */
/* 132 */	0x8,		/* FC_LONG */
			0x8,		/* FC_LONG */
/* 134 */	0x5c,		/* FC_PAD */
			0x5b,		/* FC_END */

			0x0
        }
    };

static const USER_MARSHAL_ROUTINE_QUADRUPLE UserMarshalRoutines[ WIRE_MARSHAL_TABLE_SIZE ] = 
        {
            
            {
            HWND_UserSize
            ,HWND_UserMarshal
            ,HWND_UserUnmarshal
            ,HWND_UserFree
            },
            {
            HICON_UserSize
            ,HICON_UserMarshal
            ,HICON_UserUnmarshal
            ,HICON_UserFree
            }

        };



/* Object interface: IUnknown, ver. 0.0,
   GUID={0x00000000,0x0000,0x0000,{0xC0,0x00,0x00,0x00,0x00,0x00,0x00,0x46}} */


/* Object interface: ITaskbarList, ver. 0.0,
   GUID={0x56FDF342,0xFD6D,0x11d0,{0x95,0x8A,0x00,0x60,0x97,0xC9,0xA0,0x90}} */

#pragma code_seg(".orpc")
static const unsigned short ITaskbarList_FormatStringOffsetTable[] =
    {
    0,
    30,
    66,
    102,
    138
    };

static const MIDL_STUBLESS_PROXY_INFO ITaskbarList_ProxyInfo =
    {
    &Object_StubDesc,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList_FormatStringOffsetTable[-3],
    0,
    0,
    0
    };


static const MIDL_SERVER_INFO ITaskbarList_ServerInfo = 
    {
    &Object_StubDesc,
    0,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList_FormatStringOffsetTable[-3],
    0,
    0,
    0,
    0};
CINTERFACE_PROXY_VTABLE(8) _ITaskbarListProxyVtbl = 
{
    &ITaskbarList_ProxyInfo,
    &IID_ITaskbarList,
    IUnknown_QueryInterface_Proxy,
    IUnknown_AddRef_Proxy,
    IUnknown_Release_Proxy ,
    (void *) (INT_PTR) -1 /* ITaskbarList::HrInit */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::AddTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::DeleteTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::ActivateTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::SetActiveAlt */
};

const CInterfaceStubVtbl _ITaskbarListStubVtbl =
{
    &IID_ITaskbarList,
    &ITaskbarList_ServerInfo,
    8,
    0, /* pure interpreted */
    CStdStubBuffer_METHODS
};


/* Object interface: ITaskbarList2, ver. 0.0,
   GUID={0x602D4995,0xB13A,0x429b,{0xA6,0x6E,0x19,0x35,0xE4,0x4F,0x43,0x17}} */

#pragma code_seg(".orpc")
static const unsigned short ITaskbarList2_FormatStringOffsetTable[] =
    {
    0,
    30,
    66,
    102,
    138,
    174
    };

static const MIDL_STUBLESS_PROXY_INFO ITaskbarList2_ProxyInfo =
    {
    &Object_StubDesc,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList2_FormatStringOffsetTable[-3],
    0,
    0,
    0
    };


static const MIDL_SERVER_INFO ITaskbarList2_ServerInfo = 
    {
    &Object_StubDesc,
    0,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList2_FormatStringOffsetTable[-3],
    0,
    0,
    0,
    0};
CINTERFACE_PROXY_VTABLE(9) _ITaskbarList2ProxyVtbl = 
{
    &ITaskbarList2_ProxyInfo,
    &IID_ITaskbarList2,
    IUnknown_QueryInterface_Proxy,
    IUnknown_AddRef_Proxy,
    IUnknown_Release_Proxy ,
    (void *) (INT_PTR) -1 /* ITaskbarList::HrInit */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::AddTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::DeleteTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::ActivateTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::SetActiveAlt */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList2::MarkFullscreenWindow */
};

const CInterfaceStubVtbl _ITaskbarList2StubVtbl =
{
    &IID_ITaskbarList2,
    &ITaskbarList2_ServerInfo,
    9,
    0, /* pure interpreted */
    CStdStubBuffer_METHODS
};


/* Standard interface: __MIDL_itf_ITaskbarList_0000_0002, ver. 0.0,
   GUID={0x00000000,0x0000,0x0000,{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}} */


/* Object interface: ITaskbarList3, ver. 0.0,
   GUID={0xea1afb91,0x9e28,0x4b86,{0x90,0xe9,0x9e,0x9f,0x8a,0x5e,0xef,0xaf}} */

#pragma code_seg(".orpc")
static const unsigned short ITaskbarList3_FormatStringOffsetTable[] =
    {
    0,
    30,
    66,
    102,
    138,
    174,
    216,
    264,
    306,
    348,
    384,
    426,
    474,
    522,
    570,
    612,
    660,
    702
    };

static const MIDL_STUBLESS_PROXY_INFO ITaskbarList3_ProxyInfo =
    {
    &Object_StubDesc,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList3_FormatStringOffsetTable[-3],
    0,
    0,
    0
    };


static const MIDL_SERVER_INFO ITaskbarList3_ServerInfo = 
    {
    &Object_StubDesc,
    0,
    ITaskbarList__MIDL_ProcFormatString.Format,
    &ITaskbarList3_FormatStringOffsetTable[-3],
    0,
    0,
    0,
    0};
CINTERFACE_PROXY_VTABLE(21) _ITaskbarList3ProxyVtbl = 
{
    &ITaskbarList3_ProxyInfo,
    &IID_ITaskbarList3,
    IUnknown_QueryInterface_Proxy,
    IUnknown_AddRef_Proxy,
    IUnknown_Release_Proxy ,
    (void *) (INT_PTR) -1 /* ITaskbarList::HrInit */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::AddTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::DeleteTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::ActivateTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList::SetActiveAlt */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList2::MarkFullscreenWindow */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetProgressValue */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetProgressState */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::RegisterTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::UnregisterTab */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetTabOrder */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetTabActive */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::ThumbBarAddButtons */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::ThumbBarUpdateButtons */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::ThumbBarSetImageList */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetOverlayIcon */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetThumbnailTooltip */ ,
    (void *) (INT_PTR) -1 /* ITaskbarList3::SetThumbnailClip */
};

const CInterfaceStubVtbl _ITaskbarList3StubVtbl =
{
    &IID_ITaskbarList3,
    &ITaskbarList3_ServerInfo,
    21,
    0, /* pure interpreted */
    CStdStubBuffer_METHODS
};

static const MIDL_STUB_DESC Object_StubDesc = 
    {
    0,
    NdrOleAllocate,
    NdrOleFree,
    0,
    0,
    0,
    0,
    0,
    ITaskbarList__MIDL_TypeFormatString.Format,
    1, /* -error bounds_check flag */
    0x50002, /* Ndr library version */
    0,
    0x801026e, /* MIDL Version 8.1.622 */
    0,
    UserMarshalRoutines,
    0,  /* notify & notify_flag routine table */
    0x1, /* MIDL flag */
    0, /* cs routines */
    0,   /* proxy/server info */
    0
    };

const CInterfaceProxyVtbl * const _ITaskbarList_ProxyVtblList[] = 
{
    ( CInterfaceProxyVtbl *) &_ITaskbarListProxyVtbl,
    ( CInterfaceProxyVtbl *) &_ITaskbarList3ProxyVtbl,
    ( CInterfaceProxyVtbl *) &_ITaskbarList2ProxyVtbl,
    0
};

const CInterfaceStubVtbl * const _ITaskbarList_StubVtblList[] = 
{
    ( CInterfaceStubVtbl *) &_ITaskbarListStubVtbl,
    ( CInterfaceStubVtbl *) &_ITaskbarList3StubVtbl,
    ( CInterfaceStubVtbl *) &_ITaskbarList2StubVtbl,
    0
};

PCInterfaceName const _ITaskbarList_InterfaceNamesList[] = 
{
    "ITaskbarList",
    "ITaskbarList3",
    "ITaskbarList2",
    0
};


#define _ITaskbarList_CHECK_IID(n)	IID_GENERIC_CHECK_IID( _ITaskbarList, pIID, n)

int __stdcall _ITaskbarList_IID_Lookup( const IID * pIID, int * pIndex )
{
    IID_BS_LOOKUP_SETUP

    IID_BS_LOOKUP_INITIAL_TEST( _ITaskbarList, 3, 2 )
    IID_BS_LOOKUP_NEXT_TEST( _ITaskbarList, 1 )
    IID_BS_LOOKUP_RETURN_RESULT( _ITaskbarList, 3, *pIndex )
    
}

const ExtendedProxyFileInfo ITaskbarList_ProxyFileInfo = 
{
    (PCInterfaceProxyVtblList *) & _ITaskbarList_ProxyVtblList,
    (PCInterfaceStubVtblList *) & _ITaskbarList_StubVtblList,
    (const PCInterfaceName * ) & _ITaskbarList_InterfaceNamesList,
    0, /* no delegation */
    & _ITaskbarList_IID_Lookup, 
    3,
    2,
    0, /* table of [async_uuid] interfaces */
    0, /* Filler1 */
    0, /* Filler2 */
    0  /* Filler3 */
};
#if _MSC_VER >= 1200
#pragma warning(pop)
#endif


#endif /* !defined(_M_IA64) && !defined(_M_AMD64) && !defined(_ARM_) */

