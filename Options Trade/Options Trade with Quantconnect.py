#I will be using Quantconnect platform to backtest this demo first, then import the results in the next update.

from datetime import timedelta
from QuantConnect.Data.Custom.CBOE import *

class OptionChainProviderPutProtection(QCAlgorithm):

    def Initialize(self):
        # set start/end date for backtest
        self.SetStartDate(2017, 10, 1)
        self.SetEndDate(2020, 10, 1)
        # set starting balance for backtest
        self.SetCash(100000)
        # add the underlying asset
        self.equity = self.AddEquity("SPY", Resolution.Minute)
        self.equity.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self.symbol = self.equity.Symbol
        # add VIX data
        self.vix = self.AddData(CBOE, "VIX").Symbol
        # initialize IV indicator
        self.rank = 0
        # initialize the option contract with empty string
        self.contract = str()
        self.contractsAdded = set()
        
        # parameters ------------------------------------------------------------
        self.DaysBeforeExp = 2 # number of days before expiry to exit
        self.DTE = 25 # target days till expiration
        self.OTM = 0.01 # target percentage OTM of put
        self.lookbackIV = 150 # lookback length of IV indicator
        self.IVlvl = 0.5 # enter position at this lvl of IV indicator
        self.percentage = 0.9 # percentage of portfolio for underlying asset
        self.options_alloc = 90 # 1 option for X num of shares (balanced would be 100)
        # ------------------------------------------------------------------------
    
        # schedule Plotting function 30 minutes after every market open
        self.Schedule.On(self.DateRules.EveryDay(self.symbol), \
                        self.TimeRules.AfterMarketOpen(self.symbol, 30), \
                        self.Plotting)
        # schedule VIXRank function 30 minutes after every market open
        self.Schedule.On(self.DateRules.EveryDay(self.symbol), \
                        self.TimeRules.AfterMarketOpen(self.symbol, 30), \
                        self.VIXRank)
        # warmup for IV indicator of data
        self.SetWarmUp(timedelta(self.lookbackIV)) 

    def VIXRank(self):
        history = self.History(CBOE, self.vix, self.lookbackIV, Resolution.Daily)
        # (Current - Min) / (Max - Min)
        self.rank = ((self.Securities[self.vix].Price - min(history["low"])) / (max(history["high"]) - min(history["low"])))
 
    def OnData(self, data):
        '''OnData event is the primary entry point for your algorithm. Each new data point will be pumped in here.
            Arguments:
                data: Slice object keyed by symbol containing the stock data
        '''
        if(self.IsWarmingUp):
            return
        
        # buy underlying asset
        if not self.Portfolio[self.symbol].Invested:
            self.SetHoldings(self.symbol, self.percentage)
        
        # buy put if VIX relatively high
        if self.rank > self.IVlvl:
            self.BuyPut(data)
        
        # close put before it expires
        if self.contract:
            if (self.contract.ID.Date - self.Time) <= timedelta(self.DaysBeforeExp):
                self.Liquidate(self.contract)
                self.Log("Closed: too close to expiration")
                self.contract = str()

    def BuyPut(self, data):
        # get option data
        if self.contract == str():
            self.contract = self.OptionsFilter(data)
            return
        
        # if not invested and option data added successfully, buy option
        elif not self.Portfolio[self.contract].Invested and data.ContainsKey(self.contract):
            self.Buy(self.contract, round(self.Portfolio[self.symbol].Quantity / self.options_alloc))

    def OptionsFilter(self, data):
        ''' OptionChainProvider gets a list of option contracts for an underlying symbol at requested date.
            Then you can manually filter the contract list returned by GetOptionContractList.
            The manual filtering will be limited to the information included in the Symbol
            (strike, expiration, type, style) and/or prices from a History call '''

        contracts = self.OptionChainProvider.GetOptionContractList(self.symbol, data.Time)
        self.underlyingPrice = self.Securities[self.symbol].Price
        # filter the out-of-money put options from the contract list which expire close to self.DTE num of days from now
        otm_puts = [i for i in contracts if i.ID.OptionRight == OptionRight.Put and
                                            self.underlyingPrice - i.ID.StrikePrice > self.OTM * self.underlyingPrice and
                                            self.DTE - 8 < (i.ID.Date - data.Time).days < self.DTE + 8]
        if len(otm_puts) > 0:
            # sort options by closest to self.DTE days from now and desired strike, and pick first
            contract = sorted(sorted(otm_puts, key = lambda x: abs((x.ID.Date - self.Time).days - self.DTE)),
                                                     key = lambda x: self.underlyingPrice - x.ID.StrikePrice)[0]
            if contract not in self.contractsAdded:
                self.contractsAdded.add(contract)
                # use AddOptionContract() to subscribe the data for specified contract
                self.AddOptionContract(contract, Resolution.Minute)
            return contract
        else:
            return str()

    def Plotting(self):
        # plot IV indicator
        self.Plot("Vol Chart", "Rank", self.rank)
        # plot indicator entry level
        self.Plot("Vol Chart", "lvl", self.IVlvl)
        # plot underlying's price
        self.Plot("Data Chart", self.symbol, self.Securities[self.symbol].Close)
        # plot strike of put option
        
        option_invested = [x.Key for x in self.Portfolio if x.Value.Invested and x.Value.Type==SecurityType.Option]
        if option_invested:
                self.Plot("Data Chart", "strike", option_invested[0].ID.StrikePrice)

    def OnOrderEvent(self, orderEvent):
        # log order events
        self.Log(str(orderEvent))