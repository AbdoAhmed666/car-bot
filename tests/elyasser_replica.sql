-- Replica of the ELYASSER tables the bot reads: same names and types as the
-- shop's ELyasserDB (see tools/discover.ps1 output), only the columns we use.
-- Lets the bot and the tools be tested without the shop's real data.

CREATE TABLE dbo.Z_TypeItem1 (id bigint PRIMARY KEY, aname nvarchar(100));

CREATE TABLE dbo.Item (
    id_item bigint PRIMARY KEY, ARname nvarchar(200), InternationalCode nvarchar(50),
    IdTypeItem1 bigint, PurchasePrice real, BigPr0 real, Minimum int, Day_Recession int,
    CountMiddel float, CountSmall float, Balance float, CurrentBalance0 float,
    cost real, net_balance float, Deleted bit, DateEdit date, DateCreate date);

CREATE TABLE dbo.Item_store (
    id bigint PRIMARY KEY, id_item bigint, id_store bigint,
    come_big float, come_Middel float, come_Small float,
    out_big float, out_Middel float, out_Small float,
    unit smallint, pdate datetime, id_pur bigint, id_rpur bigint, id_sal bigint, id_rsal bigint,
    pr real, Profit real);

CREATE TABLE dbo.Sal_Invoice (
    id_sal bigint PRIMARY KEY, id_store bigint, id_cust bigint, pdate datetime,
    cashDiscount decimal(18,2), AmountPaid decimal(18,2), Total decimal(18,3),
    TypePaied tinyint, Profit real);

CREATE TABLE dbo.Sal_Details (
    id bigint PRIMARY KEY, id_sal bigint, id_item bigint, unit smallint, qu float,
    pr real, Discount decimal(18,2), total_item real, profit real, id_store bigint);

CREATE TABLE dbo.sal_temp (
    id bigint PRIMARY KEY, id_sal bigint, id_item bigint, unit smallint, qu float,
    pr decimal(18,3), total_item decimal(18,3), profit decimal(18,2), pdate datetime);

CREATE TABLE dbo.Rsal_invoice (
    id_Rsal bigint PRIMARY KEY, id_store bigint, id_cust bigint, pdate datetime,
    Total decimal(18,3), Profit decimal(18,2));

CREATE TABLE dbo.Rsal_details (
    id bigint PRIMARY KEY, id_RSal bigint, id_item bigint, unit smallint, qu float,
    pr decimal(18,3), total_item decimal(18,3), Profit decimal(18,2));

CREATE TABLE dbo.Sal_Deleted (
    id bigint PRIMARY KEY, id_sal bigint, ARname nvarchar(200), UnitName nvarchar(50),
    qu float, pr decimal(18,2), pdate datetime, Cust_Name nvarchar(100));

CREATE TABLE dbo.Tree_Account (
    id bigint PRIMARY KEY, id_Account bigint, pdate datetime, des nvarchar(200),
    debt decimal(18,2), credit decimal(18,2), balance decimal(18,2), id_sal bigint, Timee datetime,
    id_CashCome bigint);

CREATE TABLE dbo.JopTime (
    id bigint PRIMARY KEY, pdate date, EndJop nvarchar(10), BeginJop nvarchar(10), UserName nvarchar(50));

CREATE TABLE dbo.ZZproperties (
    ID bigint PRIMARY KEY, PathBackup nvarchar(260), HourOfBackup int, DataBaseName nvarchar(100));

CREATE TABLE dbo.cust (
    id_cust bigint PRIMARY KEY, Aname nvarchar(200), Mobile nvarchar(50), IsCustomer tinyint,
    id_account bigint, credit_limit float, MaxDayOfCredit int, Deleted bit);

CREATE TABLE dbo.Tree (id bigint PRIMARY KEY, aname nvarchar(200), Begin_balance decimal(18,2));
