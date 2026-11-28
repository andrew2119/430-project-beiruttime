import {readAuction,readLots} from '@/features/auction-management/api';
import {definePageRead} from '@/lib/page-speed/definition';

export const listingAuctionRead=definePageRead({
  key:(listingId:string,auctionId?:string)=>auctionId
    ?['listing-auction',listingId,auctionId]:['listing-auction',listingId],
  warm:'safe',fresh:1000,
  ask:async(signal,listingId:string,auctionId?:string)=>auctionId
    ?{items:[await readAuction(auctionId,signal)]}
    :readLots(listingId,signal),
});
